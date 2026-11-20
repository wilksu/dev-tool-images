#!/bin/sh
set -eu

java -version > /tmp/java-version 2>&1
cat /tmp/java-version
grep -Eq 'version "21([.]|")' /tmp/java-version
go version | grep -Fx 'go version go1.27.4 linux/amd64'
test -r "$ANDROID_HOME/platforms/android-37.0/android.jar"
"$ANDROID_HOME/build-tools/36.0.0/aapt2" version
grep -E '^Pkg\.Revision[[:space:]]*=[[:space:]]*30\.0\.16248370[[:space:]]*$' \
    "$ANDROID_NDK_HOME/source.properties"

export GOCACHE=/tmp/go-cache GOPROXY=off GOOS=android CGO_ENABLED=1
llvm="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
cd /tmp
cat > check.go <<'GO'
package main

import "C"

//export probeVersion
func probeVersion() C.int { return 37 }

func main() {}
GO
GOARCH=arm64 CC="$llvm/aarch64-linux-android30-clang" \
    go build -trimpath -buildmode=c-shared -o arm64.so check.go
GOARCH=amd64 CC="$llvm/x86_64-linux-android30-clang" \
    go build -trimpath -buildmode=c-shared -o amd64.so check.go
"$llvm/llvm-readelf" -h arm64.so | grep -E 'Machine:.*AArch64'
"$llvm/llvm-readelf" -h amd64.so | grep -E 'Machine:.*X86-64|Machine:.*x86-64'
