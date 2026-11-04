plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.svaronam.wallabot"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.svaronam.wallabot"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "1.0.0"
    }

    // Clave fija para que cada APK nueva se instale encima de la anterior sin desinstalar.
    signingConfigs {
        create("release") {
            storeFile = file("../keystore/wallabot.jks")
            storePassword = System.getenv("KEYSTORE_PASSWORD")
            keyAlias = "wallabot"
            keyPassword = System.getenv("KEYSTORE_PASSWORD")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("release")
        }
        debug {
            signingConfig = signingConfigs.getByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
}
