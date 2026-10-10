# AGENTS

## Project Overview

- This repository is the **Android client only** for Zhengzhou University services.
- The Flutter UI lives in `flutter-app/lib/main.dart` (one large file; page classes are top level).
- Business logic runs in an embedded **Chaquopy Python 3.12** runtime under `flutter-app/android/app/src/main/python/`. All requests go from the phone straight to the school services; there is no backend in this repository.
- Android/Java side: `flutter-app/android/app/src/main/java/cn/edu/zzu/life/`.

## Layout

| Path | What it is |
| --- | --- |
| `flutter-app/lib/main.dart` | The entire Flutter UI |
| `flutter-app/android/app/src/main/python/mobile_bridge.py` | Channel entry points called from Java |
| `flutter-app/android/app/src/main/python/mobile_zzupy.py` | School service clients (CAS, EAMS, e-card) |
| `flutter-app/android/app/src/main/python/mobile_plan_page.py` | Training-plan page parsing |
| `flutter-app/android/app/src/main/java/cn/edu/zzu/life/MainActivity.java` | Platform-channel dispatch |
| `flutter-app/android/app/src/main/java/cn/edu/zzu/life/MonitorScheduler.java` | Background jobs (grade / energy checks) |
| `flutter-app/android/app/src/main/java/cn/edu/zzu/life/MonitorSettings.java` | SharedPreferences-backed settings |
| `.github/workflows/build-apk.yaml` | Builds and publishes the APK on `v*` tags |
| `.github/workflows/ci.yaml` | `flutter analyze` on push/PR |

## There Are No Automated Tests

- This repository has **no test suite** and no Python tooling. Verify changes by running `flutter analyze` and building the APK.
- Manual device verification is the real check: `adb install -r <apk>` and exercise the feature.
- If you add logic that can be checked offline, consider adding a plain-`assert` Python script under a `scripts/` directory you create, and wire it into CI. Until then, do not claim a change is verified without a build or a device run.

## Adding a Channel Method

Four edits are required, and missing one fails at runtime rather than compile time:

1. `mobile_bridge.py` — the Python function that returns a JSON string.
2. `MainActivity.java` — a `case` in the dispatch that calls it.
3. Dart — `NativeApi.call('methodName')`.
4. The UI itself.

## Python Runtime Constraints

- `zzupy.logging` needs `loguru`, which is **not** bundled into the app. Never import it, or anything that pulls it in, from `android/app/src/main/python/`.
- Dependencies are pinned in `flutter-app/android/app/build.gradle.kts` under `chaquopy { pip { ... } }`. Adding one requires a matching entry there.
- `flutter-app/android/app/src/main/python/zzupy/` is a trimmed copy of the school API clients used by the app. It is separate from any host-side Python.

## Traps Already Paid For

Discovered against live responses. Do not "simplify" these away:

- **EAMS pages inline data as JavaScript object literals, not JSON.** Single quotes, unquoted keys, and `$`-prefixed keys (`{'$type':'ResultType'}`), so `json.loads` can never work. `mobile_plan_page.py` contains a parser that accepts **data literals only** and raises on functions or variable references instead of evaluating them.
- **The school's "not passed" course result is `UNREPAIRED`**, not `FAILED`. Matching only `FAILED` silently lists zero failed courses. The three real values are `PASSED`, `UNREPAIRED`, `TAKING`.
- **Plan credit fields are `credits` / `subModuleNum`**, not `requiredCredits` / `requiredCourseNum`.
- **Grade point averages must be credit-weighted.** A plain arithmetic mean is wrong.
- **Parent and child plan modules are separate credit buckets.** Skipping a node because it has children silently drops its required credits.
- **Reusing a CAS token requires restoring MFA state too**, or `login()` raises an MFA error.

## Building The APK (Windows)

The toolchain is pinned outside the repository; `flutter-app/android/local.properties` and `gradle.properties` point at it. Set these first:

```powershell
$env:JAVA_HOME         = "E:\dev-tools\jdk-17.0.20.1+1"
$env:GRADLE_USER_HOME  = "E:\dev-tools\gradle-home"
$env:ANDROID_SDK_ROOT  = "E:\dev-tools\android-sdk"
$env:PUB_CACHE         = "D:\code\.flutter-pub-cache"
$env:PATH = "E:\dev-tools\jdk-17.0.20.1+1\bin;D:\code\.flutter-sdk-good\flutter\bin;" + $env:PATH
cd flutter-app
flutter build apk --release --target-platform android-arm64
```

- ~70s with a warm Gradle cache. If a build hangs with no file writes, check `android/local.properties` — a wrong `sdk.dir` makes AGP try to download the NDK.
- Chaquopy needs **Python 3.12** on `PATH`, or set `CHAQUOPY_BUILD_PYTHON` to its interpreter.

## Versioning And Release

- Version lives in `flutter-app/pubspec.yaml` as `versionName+versionCode`.
- **`versionCode` must never decrease.** It is currently `21`. A version code lower than the installed one makes `adb install -r` fail with `INSTALL_FAILED_VERSION_DOWNGRADE`, and the only fix is uninstalling (which wipes app data).
- `versionName` restarted at `1.0.0`. The earlier `3.x` series continued the numbering of a superseded native app and meant nothing for this project.
- `release/` and `*.apk` are gitignored: **APKs are distributed as GitHub Release assets, not committed.** Push a `v*` tag to trigger `.github/workflows/build-apk.yaml`.
- Signing: `flutter-app/android/keystore.properties` (gitignored, template `keystore.properties.example`). **Keep the keystore** — changing it breaks in-place upgrades for everyone. CI reads it from `ANDROID_KEYSTORE_BASE64` and friends; without those secrets Gradle falls back to debug signing.

## Workspace Hygiene

- Do not commit captured pages, session caches, or anything with a real student's name, ID, grades, or credentials. Debug dumps go outside the repository and must be deleted after use.
- `git status` before broad edits; the tree may hold unrelated user changes. Do not revert changes you did not make.
