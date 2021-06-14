all: package-lambda

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  package-lambda      to package the lambda function"

package-lambda:
	@echo "create lambda deployment package (vpx_stats_cloudwatch.zip)"
	rm -f vpx_stats_cloudwatch.zip
	rm -rf package/
	mkdir ./package
	cp -f citrixadcmetrics.py ./package/
	cd package && zip -r9 ../vpx_stats_cloudwatch.zip .
	@echo "****** Adding Lambda Function to ZIP ******"
	cd .. && zip -g vpx_stats_cloudwatch.zip lambda_function.py
