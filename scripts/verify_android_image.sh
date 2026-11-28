#!/usr/bin/env bash
set -euo pipefail
image=$1
work="$RUNNER_TEMP/android-fixture"
cache="$RUNNER_TEMP/android-cache"
mkdir -p "$work" "$cache"/{home,gradle,go-build,go-mod}
cp -R fixtures/android-go/. "$work/"
wrapper="$work/gradle/wrapper/gradle-wrapper.jar"
curl -fsSL --retry 3 https://raw.githubusercontent.com/gradle/gradle/v9.9.1/gradle/wrapper/gradle-wrapper.jar -o "$wrapper"
echo "621008afc4f5d59357fcf06ffa644dd5aade5e091bdc363742710445f73cdaf8  $wrapper" | sha256sum -c -
options=(--rm --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges
  --mount "type=bind,src=$work,dst=/workspace"
  --mount "type=bind,src=$cache,dst=/cache"
  -e HOME=/cache/home -e JAVA_TOOL_OPTIONS=-Duser.home=/cache/home
  -e GRADLE_USER_HOME=/cache/gradle -e GOCACHE=/cache/go-build -e GOMODCACHE=/cache/go-mod)
tasks=(--no-daemon --console=plain --no-build-cache assembleDebug testDebugUnitTest lintDebug)
docker run "${options[@]}" --network none "$image" sh /workspace/verify.sh
docker run "${options[@]}" "$image" java -cp gradle/wrapper/gradle-wrapper.jar \
  org.gradle.wrapper.GradleWrapperMain "${tasks[@]}"
rm -rf "$work/build" "$work/src/main/jniLibs"
docker run "${options[@]}" --network none -e GOPROXY=off "$image" sh -eu -c '
  sh /workspace/verify.sh
  exec java -cp gradle/wrapper/gradle-wrapper.jar org.gradle.wrapper.GradleWrapperMain "$@"
' verify --offline "${tasks[@]}"
for abi in arm64-v8a x86_64; do
  apk="$work/build/outputs/apk/debug/android-go-fixture-$abi-debug.apk"
  test -s "$apk"
  test "$(stat -c '%u:%g' "$apk")" = "$(id -u):$(id -g)"
  unzip -Z -1 "$apk" | grep -Fx "lib/$abi/libprobe.so"
done
