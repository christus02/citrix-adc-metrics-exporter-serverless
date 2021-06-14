rm vpx_stats_datadog.zip 
rm -rf package/
pip install --target ./package datadog
cp -f citrixadcmetrics.py package/
cd package && zip -r9 ../vpx_stats_datadog.zip .
echo "****** Adding Lambda Function to ZIP ******"
cd .. && zip -g vpx_stats_datadog.zip lambda_function.py 