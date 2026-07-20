$ErrorActionPreference = 'Stop'

$assignmentDir = Split-Path -Parent $PSScriptRoot
$workspaceDir = Split-Path -Parent $assignmentDir
$repoCandidate = Join-Path $workspaceDir 'secp256k1'

if (-not (Test-Path -LiteralPath (Join-Path $repoCandidate 'CMakeLists.txt') -PathType Leaf)) {
    throw "Expected the secp256k1 repository at '$repoCandidate'. Keep 'assignment-2' and 'secp256k1' as sibling directories."
}

$repoDir = (Resolve-Path -LiteralPath $repoCandidate).Path
$buildDir = Join-Path $repoDir 'build-assignment2'

Write-Host "Assignment directory: $assignmentDir"
Write-Host "secp256k1 repository: $repoDir"

Write-Host '== Configure and build =='
cmake -S $repoDir -B $buildDir -G 'MinGW Makefiles' `
    -DCMAKE_BUILD_TYPE=Release `
    -DSECP256K1_BUILD_TESTS=ON `
    -DSECP256K1_BUILD_EXHAUSTIVE_TESTS=ON `
    -DSECP256K1_BUILD_BENCHMARK=ON `
    -DSECP256K1_BUILD_EXAMPLES=ON
cmake --build $buildDir -j 4

Write-Host '== Full test suite =='
ctest --test-dir $buildDir --output-on-failure

Write-Host '== Educational demonstrations =='
python (Join-Path $PSScriptRoot 'ecdsa_hash_forgery_demo.py')
python (Join-Path $PSScriptRoot 'rfc6979_reduction_demo.py')

Write-Host '== Selected benchmarks =='
$env:SECP256K1_BENCH_ITERS = '20000'
& (Join-Path $buildDir 'bin\bench.exe') ecdsa_sign ecdsa_verify ec_keygen ecdh schnorrsig_sign schnorrsig_verify
& (Join-Path $buildDir 'bin\bench_internal.exe') scalar inverse
& (Join-Path $buildDir 'bin\bench_internal.exe') field inverse
