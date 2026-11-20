#!/bin/sh
set -eu

java -version > /tmp/java-version 2>&1
cat /tmp/java-version
grep -F 'version "21.0.13"' /tmp/java-version
go version | grep -Fx 'go version go1.27.4 linux/amd64'
test -r "$ANDROID_HOME/platforms/android-37.0/android.jar"
"$ANDROID_HOME/build-tools/36.0.0/aapt2" version
grep -E '^Pkg\.Revision[[:space:]]*=[[:space:]]*30\.0\.16248370[[:space:]]*$' \
    "$ANDROID_NDK_HOME/source.properties"

export GOTOOLCHAIN=local GOPROXY=off GOOS=android CGO_ENABLED=1
export CGO_LDFLAGS='-Wl,-z,max-page-size=16384'
llvm="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin"
jni=src/main/jniLibs
mkdir -p "$jni/arm64-v8a" "$jni/x86_64"
GOARCH=arm64 CC="$llvm/aarch64-linux-android30-clang" \
    go build -trimpath -buildmode=c-shared -o "$jni/arm64-v8a/libprobe.so" native.go
GOARCH=amd64 CC="$llvm/x86_64-linux-android30-clang" \
    go build -trimpath -buildmode=c-shared -o "$jni/x86_64/libprobe.so" native.go
"$llvm/llvm-readelf" -h "$jni/arm64-v8a/libprobe.so" | grep 'Machine:.*AArch64'
"$llvm/llvm-readelf" -h "$jni/x86_64/libprobe.so" | grep 'Machine:.*X86-64'
