import boto3
import logging
import sys
import urllib2
import os
from datetime import datetime
import json

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
    metrics_json = get_metrics_template()
    stats = {}
    for feature in metrics_json.keys():
        stats[feature] = get_feature_stats(vpx_instance_info, feature)
    return stats

def parse_stats(vpx_instance_info, metrics_json, stats):
    filled_metrics = []
    for feature in metrics_json.keys():
        if feature not in stats[feature]:
            continue;
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
    all_stats = get_all_stats(vpx_instance_info, metrics_json.keys())
    filled_metrics = parse_stats(vpx_instance_info, metrics_json, all_stats)
    return filled_metrics

def get_feature_stats(vpx_instance_info,feature):
    '''
    Method for fetch the Nitro stats from VPX
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

def make_metric(metricname, dimensions, value, unit):
    metric = {'MetricName': metricname,
              'Dimensions': dimensions,
              'Timestamp': datetime.now(),
              'Value': value,
              'Unit': unit
              }
    return metric


def make_dimensions(dims):
    dimensions = []
    for d in dims.keys():
        dimensions.append({'Name': d, 'Value': dims[d]})
    return dimensions


def get_vpx_instances(vpx_asg_name):
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


def put_aggr_stats(asg_name, stats_list):
    aggregate_stats = {}
    for stat in stats_list:
        lbstats = stat.get('lbvserver')
        if lbstats is None:
            logger.info("No stats found")
            continue
        for lbstat in lbstats:
            aggregate_stats['totalrequests'] = aggregate_stats.get('totalrequests', 0) + int(lbstat['totalrequests'])
            aggregate_stats['totalrequestbytes'] = aggregate_stats.get('totalrequestbytes', 0) + int(lbstat['totalrequestbytes'])
            aggregate_stats['curclntconnections'] = aggregate_stats.get('curclntconnections', 0) + int(lbstat['curclntconnections'])
            aggregate_stats['surgecount'] = aggregate_stats.get('surgecount', 0) + int(lbstat['surgecount'])

    dims = {'vpxasg': asg_name}
    dimensions = make_dimensions(dims)
    metricData = [make_metric('totalrequests', dimensions, aggregate_stats.get('totalrequests', 0), 'Count'),
                  make_metric('totalrequestbytes', dimensions, aggregate_stats.get('totalrequestbytes', 0), 'Count'),
                  make_metric('curclntconnections', dimensions, aggregate_stats.get('curclntconnections', 0), 'Count'),
                  make_metric('surgecount', dimensions, aggregate_stats.get('surgecount', 0), 'Count'),
                  ]
    push_out = cw_client.put_metric_data(Namespace='NetScaler', MetricData=metricData)
    logger.info("Result of Pushing Metrics to Cloud Watch: " + str(push_out))
    

def put_stats(vpx_info, stats):
    lbstats = stats.get('lbvserver')
    if lbstats is None:
        logger.info("No stats found")
        return

    for lbstat in lbstats:
        dims = {'lbname': lbstat['name'], 'vpxinstance': vpx_info['instance-id'], 'vpxasg': vpx_info['asg-name']}
        dimensions = make_dimensions(dims)
        # TODO sanitize str->int conv
        metricData = [make_metric('totalrequests', dimensions, int(lbstat['totalrequests']), 'Count'),
                      make_metric('totalrequestbytes', dimensions, int(lbstat['totalrequestbytes']), 'Count'),
                      make_metric('curclntconnections', dimensions, int(lbstat['curclntconnections']), 'Count'),
                      make_metric('surgecount', dimensions, int(lbstat['surgecount']), 'Count'),
                      make_metric('health', dimensions, int(lbstat['vslbhealth']), 'Count'),
                      make_metric('state', dimensions, (lambda s: 1 if s == 'UP' else 0)(lbstat['state']), 'Count'),
                      make_metric('actsvcs', dimensions, int(lbstat['actsvcs']), 'Count'),
                      make_metric('inactsvcs', dimensions, int(lbstat['inactsvcs']), 'Count')
                      ]
        push_out = cw_client.put_metric_data(Namespace='NetScaler', MetricData=metricData)
        logger.info("Result of Pushing Metrics to Cloud Watch: " + str(push_out))

def push_stats(metricData, namespace=CLOUDWATCH_NAMESPACE):
    push_out = cw_client.put_metric_data(Namespace=namespace, MetricData=metricData)
    logger.info("Result of Pushing Metrics to Cloud Watch: " + str(push_out))


def lambda_handler(event, context):
    logger.info(str(event))
    asg_name = "raghulc2-vpx-asg"
    #try:
    #    asg_name = os.environ['ASG_NAME']
    #except KeyError as ke:
    #    logger.warn("Bailing since we can't get the required env var: " +
    #                ke.args[0])
    #    return

    metrics_json = get_metrics_template()
    vpx_instances = get_vpx_instances(asg_name)
    for vpx in vpx_instances:
        stats = fill_up_metrics(vpx, metrics_json)
        push_stats(stats)

if __name__ == "__main__":
    event = []
    context = []
    lambda_handler(event, context)
