{
  lib,
  python313,
  python313Packages,
  stdenv,
}: let
  version = "0.1.3";

  # Python dependencies for the ticket generator
  pythonEnv = python313.withPackages (ps: with ps; [
    boto3
    botocore
  ]);

in stdenv.mkDerivation {
  pname = "ticket-generator";
  inherit version;

  src = lib.sourceByRegex ../.. [
    "^src(/.*)?$"
    "^pyproject\.toml$"
    "^README\.md$"
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
    mkdir -p $out/lib/python3.13/site-packages/src/generator
    mkdir -p $out/bin

    # Copy only generator source code (no common, no processor)
    cp -r src/generator/* $out/lib/python3.13/site-packages/src/generator/

    # Create executable wrapper
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

    # Export pythonEnv path so Python can find dependencies
    mkdir -p $out/nix-support
    cat > $out/nix-support/setup-hook << 'SETUP_HOOK'
    export PYTHONPATH="${pythonEnv}/lib/python3.13/site-packages:''${PYTHONPATH:-}"
    SETUP_HOOK

    runHook postInstall
  '';

  meta = with lib; {
    description = "Demo ticket generator for ML workload demonstration";
    longDescription = ''
      Continuously generates realistic support tickets for demonstration purposes.

      Features:
      - Generates variety of ticket types (login, payment, bug, feature, etc.)
      - Random intervals (8-15 seconds, max 7 tickets/minute)
      - Realistic templates with variable substitution
      - Uploads to S3 which triggers processor via SQS

      Ticket categories:
      - Login issues (password resets, account locks, auth errors)
      - Payment issues (double charges, refunds, failed renewals)
      - Bug reports (crashes, sync issues, corrupted exports)
      - Feature requests (new features, enhancements)
      - Account issues (profile updates, deletions)
      - Billing issues (incorrect invoices, receipt requests)

      Perfect for demonstrating the ticket processor service in action!
    '';
    homepage = "https://github.com/yourusername/localstack-ml-workload";
    license = licenses.mit;
    platforms = platforms.linux ++ platforms.darwin;
    maintainers = [];
  };
}
