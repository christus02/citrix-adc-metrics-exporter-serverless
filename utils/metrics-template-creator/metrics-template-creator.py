import json
IN_JSON = "metrics.json"
OUT_JSON = "out.json"

#Read the input metrics json
with open(IN_JSON) as f:
    metrics = json.load(f)
f.close()

unit_conversion = [
    {"key": "_mbits_rate", "value": "Megabits/Second"},
    {"key": "_mbits", "value": "Megabytes"},
    {"key": "_mb", "value": "Megabytes"},
    {"key": "_rate", "value": "Count/Second"},
    {"key": "percent", "value": "Percent"}
]

counter_template = {
    'MetricName': '',
    'Unit': 'Count',
    'Value': '',
    'Dimensions': [
        {'Name': 'Description', 'Value': ''}
        ]
}

out_ds = dict()
for feature in metrics.keys():
    out_ds[feature] = dict()
    out_ds[feature]['counters'] = list()
    for cntr in metrics[feature].get('counters', []):
        cntr_template = counter_template
        cntr_template['MetricName'] = cntr[0]
        cntr_template['Dimensions'][0]['Value'] = cntr[1]
        #Find out the right Unit
        for unit in unit_conversion:
            if unit['key'] in cntr[1]:
                cntr_template['Unit'] = unit['value']
                break
        out_ds[feature]['counters'].append(cntr_template.copy())
    for cntr in metrics[feature].get('gauges', []):
        cntr_template = counter_template
        cntr_template['MetricName'] = cntr[0]
        cntr_template['Dimensions'][0]['Value'] = cntr[1]
        #Find out the right Unit
        for unit in unit_conversion:
            if unit['key'] in cntr[1]:
                cntr_template['Unit'] = unit['value']
                break
        out_ds[feature]['counters'].append(cntr_template.copy())
    
#Read the input metrics json
with open(OUT_JSON, 'w') as f:
    json.dump(out_ds, f, indent=4)
f.close()

