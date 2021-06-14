rm vpx_stats_cloudwatch.zip 
rm -rf package/
mkdir ./package
cp -f citrixadcmetrics.py ./package/
cd package && zip -r9 ../vpx_stats_cloudwatch.zip .
echo "****** Adding Lambda Function to ZIP ******"
cd .. && zip -g vpx_stats_cloudwatch.zip lambda_function.py