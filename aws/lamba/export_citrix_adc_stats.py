import boto3
import logging
import sys
import urllib2
import os
from datetime import datetime
import json
import copy

logging.basicConfig()

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('botocore').setLevel(logging.WARNING)

ec2_client = boto3.client('ec2')
cw_client = boto3.client('cloudwatch')
asg_client = boto3.client('autoscaling')
METRICS_TEMPLATE = "https://raw.githubusercontent.com/christus02/citrix-adc-metrics-exporter-serverless/master/utils/metrics-template-creator/citrix-adc-cloudwatch-metrics-template.json"
CLOUDWATCH_NAMESPACE = 'CITRIXADC'
'''
    Use the INCLUDE_FEATURES list to specify what features stats
    to pull and push to CloudWatch
    INCLUDE_FEATURES = [] (empty list) would enable stats to be pulled
    for all the features specified in the Metrics JSON
'''
INCLUDE_FEATURES = ['system', 'protocolhttp', 'lbvserver', 'csvserver', 'service']
#INCLUDE_FEATURES = []

def get_metrics_template():
    '''
    Method to fetch the Metrics Template from a URL
    '''
    headers = {'Content-Type': 'application/json'}
    r = urllib2.Request(METRICS_TEMPLATE,  headers=headers)
    try:
        resp = urllib2.urlopen(r)
        return json.loads(resp.read())
    except urllib2.HTTPError as hte:
        logger.info("Error Fetching the metrics template : Error code: " +
                    str(hte.code) + ", reason=" + hte.reason)
    except:
        logger.warn("Caught exception: " + str(sys.exc_info()[:2]))
    return {}

def get_all_stats(vpx_instance_info, feature_list):
    '''
        Method to fetch all Nitro Stats based on the provided feature list
    '''
    stats = {}
    for feature in feature_list:
        stats[feature] = get_feature_stats(vpx_instance_info, feature)
    return stats

def parse_stats(vpx_instance_info, metrics_json, stats):
    '''
        Method to update the metrics json template with the 
        Nitro Stats got from the VPX
    '''
    filled_metrics = []
    for feature in stats.keys():
        if feature not in stats[feature]:
            continue
        for counter in metrics_json[feature]['counters']:
            filled_counter = counter
            if filled_counter['MetricName'] in stats[feature][feature]:
                filled_counter['Value'] = int(stats[feature][feature].get(filled_counter['MetricName'], 0))
                filled_counter['Timestamp'] = datetime.now()
                filled_counter['Dimensions'][1]['Value'] = vpx_instance_info['asg-name']  # AutoScale Group
                filled_counter['Dimensions'][2]['Value'] = vpx_instance_info['instance-id']  # Instance ID
                filled_metrics.append(filled_counter)
    return filled_metrics

def fill_up_metrics(vpx_instance_info, metrics_json):
    '''
        Method to fetch all the Nitro stats from the VPX
        and fill the JSON Metrics accordingly with the Nitro Stats
        Value
    '''
    features = metrics_json.keys()
    selected_features = []
    if len(INCLUDE_FEATURES) != 0:
        # Get Selective Stats only
        for feature in features:
            if feature in INCLUDE_FEATURES:
                selected_features.append(feature)
    else:
        selected_features = features

    all_stats = get_all_stats(vpx_instance_info, selected_features)
    filled_metrics = parse_stats(vpx_instance_info, metrics_json, all_stats)
    return filled_metrics

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

def split_metrics_list(metrics, size=20):
    '''
        Method to split a list into chunks of specified size
    '''
    for i in range(0, len(metrics), size):
        yield metrics[i:i + size]

def push_stats(metricData, namespace=CLOUDWATCH_NAMESPACE):
    '''
        Method to push the metrics to Cloud Watch
    '''
    if (len(metricData) > 20):
        '''
            The max metric list length is 20 for AWS CloudWatch
            So splitting list into lengths of 20 and 
            pushing multiple times if the length is greater than 20
        '''
        chuncked_metricData = split_metrics_list(metricData)
        for data in chuncked_metricData:
            push_out = cw_client.put_metric_data(Namespace=namespace, MetricData=data)
            logger.info("Result of Pushing Metrics to Cloud Watch: " + str(push_out))
    else:
        push_out = cw_client.put_metric_data(Namespace=namespace, MetricData=metricData)
        logger.info("Result of Pushing Metrics to Cloud Watch: " + str(push_out))


def lambda_handler(event, context):
    logger.info(str(event))
    try:
        asg_name = os.environ['ASG_NAME']
    except KeyError as ke:
        logger.warn("Bailing since we can't get the required env var: " +
                    ke.args[0])
        return
    '''
        1. Import the JSON Metrics Template
        2. Pull Nitro Stats from VPX(s) based on the JSON Metrics Template
        3. Fill the JSON Metrics template with the Nitro Stats value
        4. Push the Metrics to CloudWatch
    '''
    metrics_json = get_metrics_template()
    vpx_instances = get_vpx_instances(asg_name)
    for vpx in vpx_instances:
        stats = fill_up_metrics(vpx, metrics_json)
        push_stats(stats)
