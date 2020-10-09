rm vpx_stats.zip 
rm -rf package/
pip install --target ./package datadog
cp -f citrixadcmetrics.py package/
cd package && zip -r9 ../vpx_stats.zip .
echo "****** Adding Lambda Function to ZIP ******"
cd .. && zip -g vpx_stats.zip lambda_function.py 

