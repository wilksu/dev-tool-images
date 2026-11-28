# Android Go development image

This image provides Eclipse Temurin 21 on Ubuntu Noble, Go 1.27.4,
Android SDK Platform 37.0 revision 2, Android Build Tools 36.0.0, and
Android NDK 30.0.16248370. The build host is Linux amd64. The container
can produce Android arm64-v8a and x86_64 native libraries.

[`image.json`](image.json) records the upstream downloads and their
checksums. The build extracts the three pinned Android packages directly
and installs their local package descriptors derived from the SDK catalog.
Each tool is copied into its own layer. Gradle and application dependencies
are supplied by the project and stored in writable caches.

## Use the image

Set `ANDROID_GO_IMAGE` to an available image reference. For a registry or
mirror, use its full repository path and OCI digest. Set this on the host
before pulling the image.

Run this from the Android project's root, using its checked-in Gradle
Wrapper. The host owns the cache and workspace, including generated APKs.

```sh
cache="${XDG_CACHE_HOME:-$HOME/.cache}/android-go-tools"
mkdir -p "$cache/home" "$cache/gradle" "$cache/go-mod" "$cache/go-build"

docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD,dst=/workspace" \
  --mount "type=bind,src=$cache,dst=/cache" \
  -e HOME=/cache/home -e JAVA_TOOL_OPTIONS=-Duser.home=/cache/home \
  -e GRADLE_USER_HOME=/cache/gradle -e GOMODCACHE=/cache/go-mod \
  -e GOCACHE=/cache/go-build "$ANDROID_GO_IMAGE" \
  ./gradlew --no-daemon assembleDebug testDebugUnitTest lintDebug
```

The first run warms the Gradle distribution, Maven dependencies, and Go
module cache using the project's configured sources. For an offline run
with those caches, add `--network none -e GOPROXY=off` before the image
reference and `--offline` to the Gradle command. Install the resulting
APK from the host with `adb`.

## Remote verification and release

The shared CI pipeline builds this tool on Android-specific changes in pull
requests and on `master`. It warms
the fixture's Gradle cache, repeats compilation with networking disabled,
checks the native library and file ownership in each ABI's APK, and
compares OCI layers after changing only Go or SDK Platform. The reported
incremental byte counts sum the compressed descriptors for layers absent
from a warm client.

A Git tag named `android-go-tools/rev-<full-commit-sha>` verifies and
publishes that revision to `ghcr.io/wilksu/dev-tool-images/android-go-tools`.
The unified Publish pipeline copies the verified OCI runtime content and
proofs without rebuilding, and emits the same release record as the other tools.
The ACR workflow passively consumes the successful publication and copies its
runtime platforms. ACR delivery can be retried independently of publication.
The `sha-<full-commit-sha>` registry tag is a discovery handle. Pin the digest
from the GitHub Release's `release.json` or the ACR run's summary when using the
image; the ACR index omits proof descriptors and has its own recorded digest.

The image retains the component notices provided in the Android tool archives.
Google lists these archives under the Android SDK License Agreement, which
describes both the SDK distribution terms and the applicable open-source terms
for individual components.

[Android SDK terms](https://developer.android.com/studio#terms-and-conditions) ·
[NDK download and terms](https://developer.android.com/ndk/downloads)
