import json
import copy
IN_JSON = "metrics.json"
OUT_JSON = "out.json"

#Read the input metrics json
with open(IN_JSON) as f:
    metrics = json.load(f)
f.close()

UNIT_CONVERSION = [
    {"key": "_mbits_rate", "value": "Megabits/Second"},
    {"key": "_mbits", "value": "Megabytes"},
    {"key": "_mb", "value": "Megabytes"},
    {"key": "_rate", "value": "Count/Second"},
    {"key": "percent", "value": "Percent"}
]

COUNTER_TEMPLATE = {
    'MetricName': '',
    'Unit': 'Count',
    'Value': '',
    'Timestamp': '',
    'Dimensions': [
        {'Name': 'Description', 'Value': ''},
        {'Name': 'CitrixADC-AutoScale-Group', 'Value': ''},
        {'Name': 'CitrixADC-InstanceID', 'Value': ''}
    ]
}

out_ds = dict()
for feature in metrics.keys():
    out_ds[feature] = dict()
    out_ds[feature]['counters'] = list()
    for cntr in metrics[feature].get('counters', []):
        cntr_template = copy.deepcopy(COUNTER_TEMPLATE) # Deep copy is required as we have dict() of dict()
        metric_name = cntr[0]
        metric_description = cntr[1]
        cntr_template['MetricName'] = metric_name
        cntr_template['Dimensions'][0]['Value'] = metric_description
        #Find the right Unit
        for unit in UNIT_CONVERSION:
            if unit['key'] in metric_description:
                cntr_template['Unit'] = unit['value']
                break
        out_ds[feature]['counters'].append(cntr_template)
    for cntr in metrics[feature].get('gauges', []):
        cntr_template = copy.deepcopy(COUNTER_TEMPLATE) # Deep copy is required as we have dict() of dict()
        metric_name = cntr[0]
        metric_description = cntr[1]
        cntr_template['MetricName'] = metric_name
        cntr_template['Dimensions'][0]['Value'] = metric_description
        #Find the right Unit
        for unit in UNIT_CONVERSION:
            if unit['key'] in metric_description:
                cntr_template['Unit'] = unit['value']
                break
        out_ds[feature]['counters'].append(cntr_template)
    
#Write to a JSON File
with open(OUT_JSON, 'w') as f:
    json.dump(out_ds, f, indent=4)
f.close()

