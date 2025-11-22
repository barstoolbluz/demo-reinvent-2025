{
  lib,
  python313,
  python313Packages,
  stdenv,
}: let
  version = "0.1.0";

  # Python dependencies for the ticket processor
  pythonEnv = python313.withPackages (ps: with ps; [
    # Core dependencies
    boto3
    botocore
    pydantic
    pydantic-settings

    # ML dependencies
    pytorch
    torchvision
    transformers
    sentence-transformers
    numpy

    # Utility dependencies
    python-dateutil

    # Development/testing (optional for runtime)
    pytest
    hypothesis
  ]);

in stdenv.mkDerivation {
  pname = "ticket-processor";
  inherit version;

  src = lib.sourceByRegex ../.. [
    "^src(/.*)?$"
    "^setup\.py$"
    "^README\.md$"
    "^pyproject\.toml$"
  ];

  nativeBuildInputs = [
    pythonEnv
  ];

  buildInputs = [
    pythonEnv
  ];

  # No build phase needed for pure Python
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    # Create package directory
    mkdir -p $out/lib/python3.13/site-packages
    mkdir -p $out/bin

    # Copy Python source code
    cp -r src $out/lib/python3.13/site-packages/

    # Create executable wrapper
    cat > $out/bin/ticket-processor << 'EOF'
    #!${pythonEnv}/bin/python
    import sys
    sys.path.insert(0, "${pythonEnv}/lib/python3.13/site-packages")
    sys.path.insert(0, "$out/lib/python3.13/site-packages")

    from src.processor.worker import main

    if __name__ == "__main__":
        main()
    EOF

    chmod +x $out/bin/ticket-processor

    runHook postInstall
  '';

  meta = with lib; {
    description = "ML-powered support ticket enrichment processor";
    longDescription = ''
      Ticket processor that enriches support tickets with:
      - 384-dimensional semantic embeddings (sentence-transformers)
      - Intent classification (login, payment, bug, feature, etc.)
      - Urgency classification (critical, high, medium, low)
      - Sentiment analysis (positive, negative, neutral)
      - Text summarization (DistilBART)

      Integrates with AWS LocalStack for local development:
      - Polls SQS queue for ticket notifications
      - Fetches raw tickets from S3
      - Runs ML pipeline (embeddings, classification, summarization)
      - Stores enriched data in DynamoDB and S3

      CPU-optimized using distilled models (592 MB total):
      - all-MiniLM-L6-v2 (22 MB)
      - distilbert-base-uncased-finetuned-sst-2-english (255 MB)
      - distilbart-cnn-6-6 (315 MB)

      Performance:
      - 1.0s per ticket processing time
      - Up to 60 tickets/minute throughput
      - No GPU required
    '';
    homepage = "https://github.com/yourusername/localstack-ml-workload";
    license = licenses.mit;
    platforms = platforms.linux ++ platforms.darwin;
    maintainers = [];
  };
}
