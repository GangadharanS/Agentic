# TCPLT-13223: Security Fixes for MEND Vulnerabilities

## 📋 **Vulnerability Summary**
- **urllib3-1.26.18**: 3 MEDIUM vulnerabilities
- **urllib3-1.26.20**: 2 MEDIUM vulnerabilities  
- **PyMySQL-1.0.2**: 1 MEDIUM vulnerability
- **Total**: 6 MEDIUM-risk vulnerabilities

## 🎯 **Files to Update**

### 1. Maven Dependencies (pom.xml)
```xml
<!-- Update parent pom.xml or relevant module pom.xml -->
<dependencies>
    <!-- Fix urllib3 vulnerabilities -->
    <dependency>
        <groupId>org.python</groupId>
        <artifactId>jython-standalone</artifactId>
        <version>2.7.3</version>
        <exclusions>
            <exclusion>
                <groupId>urllib3</groupId>
                <artifactId>*</artifactId>
            </exclusion>
        </exclusions>
    </dependency>
    
    <!-- Add secure urllib3 version -->
    <dependency>
        <groupId>urllib3</groupId>
        <artifactId>urllib3</artifactId>
        <version>2.1.0</version>
    </dependency>
    
    <!-- Fix PyMySQL vulnerability -->
    <dependency>
        <groupId>mysql</groupId>
        <artifactId>mysql-connector-java</artifactId>
        <version>8.0.33</version>
    </dependency>
</dependencies>
```

### 2. Python Dependencies (if present)
If there are Python build tools or test dependencies:

**requirements.txt** or **requirements-dev.txt**:
```txt
# Replace vulnerable versions
urllib3>=2.1.0  # was 1.26.18/1.26.20
PyMySQL>=1.1.0  # was 1.0.2

# Other dependencies...
```

**pyproject.toml**:
```toml
[build-system]
requires = [
    "urllib3>=2.1.0",
    "PyMySQL>=1.1.0"
]
```

### 3. Gradle Dependencies (if using Gradle)
**build.gradle**:
```gradle
dependencies {
    // Exclude vulnerable versions
    configurations.all {
        exclude group: 'urllib3', version: '1.26.18'
        exclude group: 'urllib3', version: '1.26.20'
        exclude group: 'PyMySQL', version: '1.0.2'
    }
    
    // Add secure versions
    implementation 'urllib3:urllib3:2.1.0'
    implementation 'mysql:mysql-connector-java:8.0.33'
}
```

## 🚀 **Implementation Steps**

1. **Clone and checkout the branch**:
```bash
git clone https://bitbucket.trimble.tools/scm/tc/trimble-connect-files-service.git
cd trimble-connect-files-service
git checkout TCPLT-13223
```

2. **Locate dependency files**:
```bash
# Find Maven files
find . -name "pom.xml" -type f

# Find Python files  
find . -name "requirements*.txt" -type f
find . -name "pyproject.toml" -type f

# Find Gradle files
find . -name "build.gradle*" -type f
```

3. **Update each file** with secure versions shown above

4. **Test the changes**:
```bash
# Maven
mvn clean compile test

# If Python components exist
pip install -r requirements.txt
python -m pytest

# Gradle
./gradlew clean build test
```

5. **Commit and push**:
```bash
git add .
git commit -m "TCPLT-13223: Fix MEND security vulnerabilities

- Update urllib3 from 1.26.18/1.26.20 to 2.1.0 (fixes 5 MEDIUM vulns)
- Update PyMySQL from 1.0.2 to 1.1.0 (fixes 1 MEDIUM vuln)  
- Addresses MEND project token bbf4c3d2-6651-4b0f-98a0-d455782e5341
- Total vulnerabilities resolved: 6

Fixes: TCPLT-13223"

git push origin TCPLT-13223
```

## 📝 **Next Steps**
1. Create Pull Request from `TCPLT-13223` to `master`
2. Link PR to JIRA ticket TCPLT-13223
3. Request security team review
4. Run MEND scan on new branch to verify fixes
5. Merge after approval

## 🔍 **Verification**
After applying fixes, run MEND scan to confirm vulnerabilities are resolved:
- Target: 0 vulnerabilities  
- Expected: All 6 MEDIUM vulnerabilities should be resolved 