{
  description = "MCP server for the Bambuddy 3D print management API";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs =
    { self, nixpkgs }:
    let
      supportedSystems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3;
        in
        {
          default = python.pkgs.buildPythonApplication {
            pname = "bambuddy-mcp";
            version = "0.2.0";
            pyproject = true;
            src = self;

            build-system = [ python.pkgs.hatchling ];
            dependencies = [
              python.pkgs.httpx
              python.pkgs.mcp
            ];
            nativeCheckInputs = [
              pkgs.ruff
              python.pkgs.pytestCheckHook
              python.pkgs.pytest-asyncio
              python.pkgs.respx
            ];

            preCheck = ''
              ruff check src tests
              ruff format --check src tests
            '';
            pytestFlags = [ "tests" ];
            pythonImportsCheck = [ "bambuddy_mcp" ];

            meta = {
              description = "MCP server for the Bambuddy 3D print management API";
              homepage = "https://github.com/kahlstrm/bambuddy-mcp";
              license = nixpkgs.lib.licenses.gpl3Plus;
              mainProgram = "bambuddy-mcp";
            };
          };
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/bambuddy-mcp";
          meta.description = "Run the Bambuddy MCP server";
        };
      });

      checks = forAllSystems (system: {
        default = self.packages.${system}.default;
      });

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3;
          pythonEnv = python.withPackages (ps: [
            ps.httpx
            ps.mcp
            ps.pytest
            ps.pytest-asyncio
            ps.respx
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.ruff
              pythonEnv
            ];
            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt-tree);
    };
}
