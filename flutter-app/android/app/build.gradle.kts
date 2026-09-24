plugins {
    id("com.android.application")
    id("com.chaquo.python")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "cn.edu.zzu.life"
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "cn.edu.zzu.life"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = 26
        targetSdk = 35
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        ndk {
            abiFilters.clear()
            abiFilters += "arm64-v8a"
        }
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

chaquopy {
    defaultConfig {
        version = "3.12"
        // Chaquopy normally discovers Python 3.12 from PATH. Override it for
        // unusual local setups without committing a machine-specific path.
        System.getenv("CHAQUOPY_BUILD_PYTHON")
            ?.takeIf { it.isNotBlank() }
            ?.let { buildPython(it) }
        pip {
            options("--no-deps")
            install("cryptography==42.0.8")
            install("cffi==1.17.1")
            install("chaquopy-libffi==3.3")
        }
    }
}

tasks.matching { it.name == "installReleasePythonRequirements" }.configureEach {
    doFirst {
        val helper = file("$buildDir/python/env/release/Lib/site-packages/chaquopy/pip_install.py")
        if (helper.exists()) {
            var source = helper.readText(Charsets.UTF_8)
            source = source.replace("import re\nimport subprocess", "import re\nimport shutil\nimport subprocess")
            source = source.replace(
                "def renames(src, dst):\n    os.renames(src, dst)",
                "def renames(src, dst):\n" +
                    "    os.makedirs(dirname(dst), exist_ok=True)\n" +
                    "    if isdir(src):\n" +
                    "        shutil.copytree(src, dst, dirs_exist_ok=True)\n" +
                    "        rmtree(src)\n" +
                    "    else:\n" +
                    "        shutil.copy2(src, dst)\n" +
                    "        os.remove(src)"
            )
            helper.writeText(source, Charsets.UTF_8)
        }
    }
}
