{
  description = "ReInvent 2025 Demo - ML-powered support ticket enrichment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages = {
          ticket-generator = pkgs.callPackage ./.flox/pkgs/reinvent-demo-ticket-generator.nix { };
          ticket-processor = pkgs.callPackage ./.flox/pkgs/reinvent-demo-ticket-processor.nix { };

          default = self.packages.${system}.ticket-processor;
        };

        # For development
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python313
            python313Packages.boto3
            python313Packages.pydantic
            python313Packages.pytorch
            python313Packages.transformers
          ];
        };
      }
    );
}
