{
  lib,
  python313,
  python313Packages,
  stdenv,
}: let
  version = "0.1.2";

  # Combined Python dependencies for both generator and processor
  pythonEnv = python313.withPackages (ps: with ps; [
    # Core dependencies (shared)
    boto3
    botocore
    pydantic
    pydantic-settings

    # ML dependencies (processor)
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
  pname = "ticket-system";
  inherit version;

  src = lib.sourceByRegex ../.. [
    "^src(/.*)?$"
    "^setup\.py$"
    "^README\.md$"
    "^pyproject\.toml$"
    "^Makefile$"
    "^scripts(/.*)?$"
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
    mkdir -p $out/share/setup

    # Copy Python source code (includes common, generator, processor)
    cp -r src $out/lib/python3.13/site-packages/

    # Copy setup scripts and Makefile
    cp Makefile $out/share/setup/
    cp -r scripts $out/share/setup/

    # Create ticket-generator executable wrapper
    cat > $out/bin/ticket-generator << EOF
    #!${pythonEnv}/bin/python
    import sys
    sys.path.insert(0, "${pythonEnv}/lib/python3.13/site-packages")
    sys.path.insert(0, "$out/lib/python3.13/site-packages")

    from src.generator.ticket_generator import main

    if __name__ == "__main__":
        main()
    EOF

    chmod +x $out/bin/ticket-generator

    # Create ticket-processor executable wrapper
    cat > $out/bin/ticket-processor << EOF
    #!${pythonEnv}/bin/python
    import sys
    sys.path.insert(0, "${pythonEnv}/lib/python3.13/site-packages")
    sys.path.insert(0, "$out/lib/python3.13/site-packages")

    from src.processor.worker import main

    if __name__ == "__main__":
        main()
    EOF

    chmod +x $out/bin/ticket-processor

    # Export pythonEnv path so Python can find dependencies
    mkdir -p $out/nix-support
    cat > $out/nix-support/setup-hook << 'SETUP_HOOK'
    export PYTHONPATH="${pythonEnv}/lib/python3.13/site-packages:''${PYTHONPATH:-}"
    SETUP_HOOK

    runHook postInstall
  '';

  meta = with lib; {
    description = "Combined ML-powered support ticket system (generator + processor)";
    longDescription = ''
      Complete ticket system with generator and processor components.

      Ticket Generator:
      - Generates realistic support tickets for demonstration
      - Random intervals (8-15 seconds, max 7 tickets/minute)
      - Uploads to S3 which triggers processor via SQS

      Ticket Processor:
      - Enriches tickets with ML-powered analysis
      - 384-dimensional semantic embeddings (sentence-transformers)
      - Intent classification (login, payment, bug, feature, etc.)
      - Urgency classification (critical, high, medium, low)
      - Sentiment analysis (positive, negative, neutral)
      - Text summarization (DistilBART)

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
