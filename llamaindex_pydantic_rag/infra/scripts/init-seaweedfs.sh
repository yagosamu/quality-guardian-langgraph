#!/bin/bash
# Dummy credentials — SeaweedFS S3 gateway doesn't enforce auth, but the aws CLI
# refuses to run without some credentials/region configured.
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-dataops}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-dataops123}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# Wait for SeaweedFS to be ready (aws-cli only, no curl dependency in this image)
until aws --endpoint-url http://seaweedfs:8333 s3 ls > /dev/null 2>&1; do
    echo "Waiting for SeaweedFS..."
    sleep 2
done

# Create bucket via S3 API
aws --endpoint-url http://seaweedfs:8333 s3 mb s3://dataops-lake 2>/dev/null || true

# Upload seed governance documents so the ingestion pipeline (Memory engine)
# has real unstructured docs to index.
if [ -d /docs ]; then
    aws --endpoint-url http://seaweedfs:8333 s3 cp /docs s3://dataops-lake/docs/ --recursive
fi

echo "SeaweedFS bucket 'dataops-lake' ready."
