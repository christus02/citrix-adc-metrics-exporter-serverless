import boto3
import logging
import sys
import urllib2
import os
from datetime import datetime
import json
import copy
from datadog import initialize, api
import citrixadcmetrics as metrics_template

logging.basicConfig()

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)

ec2_client = boto3.client('ec2')
asg_client = boto3.client('autoscaling')
DATADOG_PREFIX = 'citrixadc'
'''
    Use the INCLUDE_FEATURES list to specify what features stats
    to pull and push to Datadog
    INCLUDE_FEATURES = [] (empty list) would enable stats to be pulled
    for all the features specified in the Metrics JSON
'''
INCLUDE_FEATURES = ['system', 'protocolhttp', 'lbvserver', 'csvserver']
#INCLUDE_FEATURES = []

DATADOG_TEMPLATE = {
    "metric": "",
    "description": "",
    "type": "",
    "points": "",
    "host": "",
    "tags": [
        "CitrixADC-AutoScale-Group:autoscalegroup",
        "Source:AWS"
    ]
}

def parse_stats_datadog(vpx_instance_info, metrics, stats):
    '''
        Method to update the metrics json template with the 
        Nitro Stats got from the VPX
        DATADOG_TEMPLATE = {
            "metric": "",
            "description": "",
            "type": "",
            "points": "",
            "host": "",
            "tags": [
                "CitrixADC-AutoScale-Group:autoscalegroup",
                "Source:AWS"
            ]
        }
    '''
    filled_metrics = []
    for feature in stats.keys():
        for counter in metrics[feature]:
            filled_counter = copy.deepcopy(DATADOG_TEMPLATE)
            if type(stats[feature][feature]) == list:
                filled_counter['metric'] = counter['MetricName']
                filled_counter['description'] = counter['Description']
                filled_counter['type'] = counter['Type'].lower()
                filled_counter = get_each_stats_datadog(filled_counter, stats[feature][feature], feature, vpx_instance_info)
                filled_metrics.extend(filled_counter) # Extend the list - Don't append
                continue
            # Counter is from the input metrics template
            # filled_counter is the DATADOG_TEMPLATE which is being filled
            if counter['MetricName'] in stats[feature][feature]:
                filled_counter['metric'] = counter['MetricName']
                filled_counter['description'] = counter['Description']
                filled_counter['type'] = counter['Type'].lower()
                filled_counter['points'] = int(stats[feature][feature].get(filled_counter['metric'], 0))
                filled_counter['host'] = vpx_instance_info['instance-id']  # Instance ID
                filled_counter['tags'][0] = "CitrixADC-AutoScale-Group:" + vpx_instance_info['asg-name']
                filled_counter['metric'] = DATADOG_PREFIX + '.' + filled_counter['metric']  # Prefix with citrixadc for each metric
                filled_metrics.append(filled_counter)
    return filled_metrics

def get_each_stats_datadog(filled_counter, stats, feature, vpx_instance_info):
    '''
        Method to iterate through the list of entities and create metrics
    '''
    filled_metrics = []
    for each_stat in stats:
        if filled_counter['metric'] in each_stat:
            filled_counter['points'] = int(each_stat.get(filled_counter['metric'], 0))
            filled_counter['host'] = vpx_instance_info['instance-id']  # Instance ID
            filled_counter['tags'][0] = "CitrixADC-AutoScale-Group:" + vpx_instance_info['asg-name']
            # Assuming we have only 2 tags set
            if len(filled_counter['tags']) == 3:
                filled_counter['tags'][2] = feature + ":" + each_stat['name']
            elif len(filled_counter['tags']) == 2:
                filled_counter['tags'].append(feature + ":" + each_stat['name']) # Add a tag with feature:name
            filled_counter['metric'] = DATADOG_PREFIX + '.' + filled_counter['metric']  # Prefix with citrixadc for each metric
            filled_metrics.append(filled_counter)
    return filled_metrics

def push_metrics_datadog(vpx, metrics, stats):
    filled_metrics = parse_stats_datadog(vpx, metrics, stats)
    post_datadog_metrics_data(filled_metrics)

def pull_citrixadc_metrics(vpx, features):
    stats = {}
    for feature in features:
        stats[feature] = get_feature_stats(vpx, feature)
    return stats

def get_feature_stats(vpx_instance_info,feature):
    '''
        Method to fetch feature specific Nitro stats from VPX
    '''
    REQUEST_METHOD = "http"  # Choose protocol as http or https
    CITRIX_ADC_USERNAME = "nsroot"
    CITRIX_ADC_PASSWORD = vpx_instance_info['instance-id']
    NSIP = vpx_instance_info['nsip']

    if vpx_instance_info['nsip-public'] is not "":
        logger.info("Getting Stats from VPX over it's public NSIP " + vpx_instance_info['nsip-public'])
        NSIP = vpx_instance_info['nsip-public']

    url = '{}://{}/nitro/v1/stat/{}/'.format(REQUEST_METHOD, NSIP, feature)
    headers = {'Content-Type': 'application/json', 'X-NITRO-USER': CITRIX_ADC_USERNAME, 'X-NITRO-PASS': CITRIX_ADC_PASSWORD}
    r = urllib2.Request(url,  headers=headers)
    try:
        resp = urllib2.urlopen(r)
        return json.loads(resp.read())
    except urllib2.HTTPError as hte:
        logger.info("Error getting stats : Error code: " +
                    str(hte.code) + ", reason=" + hte.reason)
    except:
        logger.warn("Caught exception: " + str(sys.exc_info()[:2]))
    return {}

def get_vpx_instances(vpx_asg_name):
    '''
        Get all the VPX instances in the provided AutoScale Group
    '''
    result = []
    logger.info("Looking for instances in ASG:" + vpx_asg_name)
    groups = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[vpx_asg_name])
    for group in groups['AutoScalingGroups']:
        instances = group['Instances']
        for instance in instances:
            instance_info = {}
            instance_id = instance['InstanceId']
            instance_info['instance-id'] = instance_id
            instance_info['asg-name'] = vpx_asg_name
            instance_info['availability-zone'] = instance['AvailabilityZone']
            ec2_reservations = ec2_client.describe_instances(InstanceIds=[instance_id])
            for reservation in ec2_reservations['Reservations']:
                ec2_instances = reservation['Instances']
                for ec2_instance in ec2_instances:
                    ec2_instance_id = ec2_instance['InstanceId']
                    logger.info("Found ec2_instance " + ec2_instance_id +
                                " in ASG " + vpx_asg_name + ", state=" +
                                ec2_instance['State']['Name'])
                    if ec2_instance['State']['Name'] != 'running':
                        continue
                    net_if = ec2_instance['NetworkInterfaces'][0]  # Assume interface #0 = nsip
                    logger.info("Found net interface for " + ec2_instance_id +
                                ", state=" + net_if['Status'])
                    if net_if['Status'] == 'in-use':
                        nsip_public = net_if['PrivateIpAddresses'][0].get('Association',{})
                        nsip_public = nsip_public.get('PublicIp', "")
                        nsip = net_if['PrivateIpAddresses'][0]['PrivateIpAddress']
                        logger.info("Found Private NSIP ip for " + ec2_instance_id + ": " + nsip)
                        instance_info['nsip'] = nsip
                        instance_info['nsip-public'] = nsip_public
                        if nsip_public is not "":
                            logger.info("Found Public NSIP ip for " + ec2_instance_id + ": " + nsip_public)
                        result.append(instance_info)
    return result

def post_datadog_metrics_data(metricData):
    push_out = api.Metric.send(metricData)
    logger.info("Result of Pushing Metrics to Datadog: " + str(push_out))

def lambda_handler(event, context):
    logger.info(str(event))

    # Check if Autoscale Group is provided in the ENV
    try:
        asg_name = os.environ['ASG_NAME']
    except KeyError as ke:
        logger.warn("Bailing since Autoscaling Group name was not provided in the ENV var: " +
                    ke.args[0])
        return

    # Check if Datadog's API Key is provided in the ENV
    try:
        DATADOG_API_KEY = os.environ['DATADOG_API_KEY']
    except KeyError as ke:
        logger.warn("Bailing since DATADOG API Key was not provided in the ENV var: " +
                    ke.args[0])
        return
    
    logger.info("Initializing the Datadog API")
    # Datadog Configs
    options = {
        'api_key': DATADOG_API_KEY
    }
    initialize(**options)

    '''
        1. Use the Metrics Template bundled with the Lambda package
        2. Pull Nitro Stats from VPX(s) based on the Metrics Template
        3. Fill the Metrics template with the Nitro Stats value
        4. Push the Metrics to Datadog
    '''
    # Import the Metrics Template from the Lambda deployment package
    metrics = metrics_template.metrics
    
    # Filter out the included features alone
    features = metrics.keys()
    selected_features = []
    if len(INCLUDE_FEATURES) != 0:
        for feature in features:
            if feature in INCLUDE_FEATURES:
                selected_features.append(feature)
    else:
        selected_features = features

    # Get all Citrix ADC VPX from the provided AWS Autoscale Group
    vpx_instances = get_vpx_instances(asg_name)
    for vpx in vpx_instances:
        stats = pull_citrixadc_metrics(vpx, selected_features)
        push_metrics_datadog(vpx, metrics, stats)
