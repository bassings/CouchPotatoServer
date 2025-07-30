#!/usr/bin/env python3
"""
CouchPotato Security Audit Tool

This script performs comprehensive security auditing for the CouchPotato Python 3.12 migration,
identifying potential security vulnerabilities and providing remediation guidance.

Usage:
    python3 security_audit.py --scan           # Run security scan
    python3 security_audit.py --fix            # Apply automatic fixes
    python3 security_audit.py --report         # Generate security report
"""

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
import warnings


class SecurityAuditor:
    """Comprehensive security auditor for CouchPotato Python 3.12 migration."""
    
    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.couchpotato_dir = self.project_root / "couchpotato"
        self.findings = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "info": []
        }
        
        # Security patterns to detect
        self.security_patterns = {
            "hardcoded_secrets": [
                r'password\s*=\s*["\'][^"\']+["\']',
                r'api_key\s*=\s*["\'][^"\']+["\']',
                r'secret\s*=\s*["\'][^"\']+["\']',
                r'token\s*=\s*["\'][^"\']+["\']',
            ],
            "insecure_random": [
                r'random\.random\(\)',
                r'random\.randint\(',
                r'random\.choice\(',
            ],
            "sql_injection": [
                r'execute\([^)]*%[^)]*\)',
                r'query\([^)]*%[^)]*\)',
                r'SELECT.*\+.*',
                r'INSERT.*\+.*',
            ],
            "command_injection": [
                r'os\.system\([^)]*\+',
                r'subprocess\.call\([^)]*\+',
                r'os\.popen\([^)]*\+',
            ],
            "path_traversal": [
                r'open\([^)]*\.\.[^)]*\)',
                r'file\([^)]*\.\.[^)]*\)',
            ],
            "unsafe_deserialization": [
                r'pickle\.loads?\(',
                r'cPickle\.loads?\(',
                r'eval\(',
                r'exec\(',
            ],
            "insecure_ssl": [
                r'ssl_verify\s*=\s*False',
                r'verify\s*=\s*False',
                r'CERT_NONE',
            ]
        }
    
    def scan_hardcoded_secrets(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for hardcoded secrets in source code."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["hardcoded_secrets"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line, re.IGNORECASE):
                        # Exclude comments and test files
                        if not line.strip().startswith('#') and 'test' not in str(file_path).lower():
                            findings.append({
                                "type": "hardcoded_secret",
                                "severity": "critical",
                                "file": str(file_path),
                                "line": line_num,
                                "description": f"Potential hardcoded secret detected: {line.strip()}",
                                "recommendation": "Move sensitive data to environment variables or secure configuration"
                            })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_insecure_random(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for insecure random number generation."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["insecure_random"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": "insecure_random",
                            "severity": "high",
                            "file": str(file_path),
                            "line": line_num,
                            "description": f"Insecure random number generation: {line.strip()}",
                            "recommendation": "Use secrets.SystemRandom() or os.urandom() for cryptographic purposes"
                        })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_sql_injection(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for potential SQL injection vulnerabilities."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["sql_injection"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": "sql_injection",
                            "severity": "critical",
                            "file": str(file_path),
                            "line": line_num,
                            "description": f"Potential SQL injection: {line.strip()}",
                            "recommendation": "Use parameterized queries or ORM methods"
                        })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_command_injection(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for potential command injection vulnerabilities."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["command_injection"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": "command_injection",
                            "severity": "critical",
                            "file": str(file_path),
                            "line": line_num,
                            "description": f"Potential command injection: {line.strip()}",
                            "recommendation": "Use subprocess with shell=False and validate inputs"
                        })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_unsafe_deserialization(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for unsafe deserialization patterns."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["unsafe_deserialization"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": "unsafe_deserialization",
                            "severity": "high",
                            "file": str(file_path),
                            "line": line_num,
                            "description": f"Unsafe deserialization/code execution: {line.strip()}",
                            "recommendation": "Avoid pickle, eval, exec. Use JSON or implement safe deserialization"
                        })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_insecure_ssl(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan for insecure SSL/TLS configurations."""
        findings = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            lines = content.split('\n')
            
            for pattern in self.security_patterns["insecure_ssl"]:
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        findings.append({
                            "type": "insecure_ssl",
                            "severity": "high",
                            "file": str(file_path),
                            "line": line_num,
                            "description": f"Insecure SSL/TLS configuration: {line.strip()}",
                            "recommendation": "Enable SSL verification and use secure SSL contexts"
                        })
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return findings
    
    def scan_file_permissions(self) -> List[Dict[str, Any]]:
        """Scan for insecure file permissions."""
        findings = []
        
        sensitive_files = [
            "CouchPotato.py",
            "config/*.conf",
            "data/**/*.db",
        ]
        
        for pattern in sensitive_files:
            for file_path in self.project_root.glob(pattern):
                if file_path.is_file():
                    stat = file_path.stat()
                    mode = oct(stat.st_mode)[-3:]
                    
                    # Check for world-readable sensitive files
                    if mode[2] in ['4', '5', '6', '7']:  # World readable
                        findings.append({
                            "type": "insecure_permissions",
                            "severity": "medium",
                            "file": str(file_path),
                            "description": f"File has world-readable permissions: {mode}",
                            "recommendation": "Remove world-readable permissions for sensitive files"
                        })
        
        return findings
    
    def scan_dependency_vulnerabilities(self) -> List[Dict[str, Any]]:
        """Scan for known vulnerabilities in dependencies."""
        findings = []
        
        try:
            # Run safety check on requirements files
            req_files = [
                "requirements-dev.txt",
                "requirements-python3-secure.txt"
            ]
            
            for req_file in req_files:
                req_path = self.project_root / req_file
                if req_path.exists():
                    result = subprocess.run(
                        ["safety", "check", "-r", str(req_path), "--json"],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode != 0 and result.stdout:
                        try:
                            vulnerabilities = json.loads(result.stdout)
                            for vuln in vulnerabilities:
                                findings.append({
                                    "type": "dependency_vulnerability",
                                    "severity": "high",
                                    "file": req_file,
                                    "description": f"Vulnerable dependency: {vuln.get('package', 'unknown')} - {vuln.get('vulnerability', 'unknown')}",
                                    "recommendation": f"Update to version {vuln.get('fixed_versions', ['latest'])[0] if vuln.get('fixed_versions') else 'latest'}"
                                })
                        except json.JSONDecodeError:
                            pass
        
        except FileNotFoundError:
            findings.append({
                "type": "missing_tool",
                "severity": "info",
                "description": "safety tool not found - install with: pip install safety",
                "recommendation": "Install security scanning tools"
            })
        
        return findings
    
    def run_bandit_scan(self) -> List[Dict[str, Any]]:
        """Run bandit security scanner."""
        findings = []
        
        try:
            result = subprocess.run(
                ["bandit", "-r", str(self.couchpotato_dir), "-f", "json"],
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                try:
                    bandit_results = json.loads(result.stdout)
                    for result_item in bandit_results.get("results", []):
                        severity_map = {
                            "HIGH": "high",
                            "MEDIUM": "medium",
                            "LOW": "low"
                        }
                        
                        findings.append({
                            "type": "bandit_finding",
                            "severity": severity_map.get(result_item.get("issue_severity", "low"), "low"),
                            "file": result_item.get("filename", "unknown"),
                            "line": result_item.get("line_number", 0),
                            "description": f"Bandit: {result_item.get('issue_text', 'Security issue detected')}",
                            "recommendation": "Review bandit findings and apply recommended fixes"
                        })
                except json.JSONDecodeError:
                    pass
        
        except FileNotFoundError:
            findings.append({
                "type": "missing_tool",
                "severity": "info",
                "description": "bandit tool not found - install with: pip install bandit",
                "recommendation": "Install security scanning tools"
            })
        
        return findings
    
    def scan_codebase(self) -> Dict[str, List[Dict[str, Any]]]:
        """Perform comprehensive security scan of the codebase."""
        print("🔍 Starting comprehensive security scan...")
        
        all_findings = []
        
        # Get all Python files
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        
        for file_path in python_files:
            print(f"Scanning {file_path}")
            
            # Run all security scans on each file
            all_findings.extend(self.scan_hardcoded_secrets(file_path))
            all_findings.extend(self.scan_insecure_random(file_path))
            all_findings.extend(self.scan_sql_injection(file_path))
            all_findings.extend(self.scan_command_injection(file_path))
            all_findings.extend(self.scan_unsafe_deserialization(file_path))
            all_findings.extend(self.scan_insecure_ssl(file_path))
        
        # Run system-wide scans
        all_findings.extend(self.scan_file_permissions())
        all_findings.extend(self.scan_dependency_vulnerabilities())
        all_findings.extend(self.run_bandit_scan())
        
        # Categorize findings by severity
        categorized_findings = {
            "critical": [],
            "high": [],
            "medium": [],
            "low": [],
            "info": []
        }
        
        for finding in all_findings:
            severity = finding.get("severity", "low")
            categorized_findings[severity].append(finding)
        
        return categorized_findings
    
    def apply_automatic_fixes(self) -> Dict[str, int]:
        """Apply automatic security fixes where possible."""
        print("🔧 Applying automatic security fixes...")
        
        fixes_applied = {
            "insecure_random": 0,
            "insecure_ssl": 0,
            "file_permissions": 0
        }
        
        # Fix insecure random usage
        python_files = list(self.couchpotato_dir.rglob("*.py"))
        
        for file_path in python_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                original_content = content
                
                # Replace insecure random with secure alternatives
                replacements = [
                    (r'import random\b', 'import secrets'),
                    (r'random\.random\(\)', 'secrets.SystemRandom().random()'),
                    (r'random\.randint\(([^)]+)\)', r'secrets.SystemRandom().randint(\1)'),
                    (r'random\.choice\(([^)]+)\)', r'secrets.choice(\1)'),
                ]
                
                for pattern, replacement in replacements:
                    if re.search(pattern, content):
                        content = re.sub(pattern, replacement, content)
                        fixes_applied["insecure_random"] += 1
                
                # Fix insecure SSL settings
                ssl_replacements = [
                    (r'ssl_verify\s*=\s*False', 'ssl_verify=True'),
                    (r'verify\s*=\s*False', 'verify=True'),
                ]
                
                for pattern, replacement in ssl_replacements:
                    if re.search(pattern, content):
                        content = re.sub(pattern, replacement, content)
                        fixes_applied["insecure_ssl"] += 1
                
                # Write back if changes were made
                if content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
            
            except Exception as e:
                print(f"Error fixing {file_path}: {e}")
        
        # Fix file permissions
        sensitive_files = [
            self.project_root / "CouchPotato.py",
        ]
        
        for file_path in sensitive_files:
            if file_path.exists():
                try:
                    # Set secure permissions (owner read/write only)
                    file_path.chmod(0o600)
                    fixes_applied["file_permissions"] += 1
                except Exception as e:
                    print(f"Error fixing permissions for {file_path}: {e}")
        
        return fixes_applied
    
    def generate_security_report(self, findings: Dict[str, List[Dict[str, Any]]]) -> str:
        """Generate comprehensive security report."""
        report = []
        report.append("# CouchPotato Security Audit Report")
        report.append("=" * 50)
        report.append("")
        
        # Summary
        total_findings = sum(len(findings_list) for findings_list in findings.values())
        report.append(f"## Executive Summary")
        report.append(f"Total security findings: {total_findings}")
        report.append("")
        
        for severity in ["critical", "high", "medium", "low", "info"]:
            count = len(findings[severity])
            if count > 0:
                report.append(f"- {severity.title()}: {count}")
        report.append("")
        
        # Detailed findings
        for severity in ["critical", "high", "medium", "low", "info"]:
            if findings[severity]:
                report.append(f"## {severity.title()} Severity Issues")
                report.append("-" * 30)
                
                for i, finding in enumerate(findings[severity], 1):
                    report.append(f"### {i}. {finding.get('type', 'Unknown').replace('_', ' ').title()}")
                    report.append(f"**File:** {finding.get('file', 'N/A')}")
                    if finding.get('line'):
                        report.append(f"**Line:** {finding['line']}")
                    report.append(f"**Description:** {finding.get('description', 'N/A')}")
                    report.append(f"**Recommendation:** {finding.get('recommendation', 'N/A')}")
                    report.append("")
        
        # Security recommendations
        report.append("## Security Hardening Recommendations")
        report.append("-" * 40)
        report.append("")
        report.append("1. **Secrets Management:**")
        report.append("   - Move all secrets to environment variables")
        report.append("   - Use a secrets management system in production")
        report.append("   - Implement secret rotation policies")
        report.append("")
        report.append("2. **Cryptographic Security:**")
        report.append("   - Use secrets module for cryptographic random numbers")
        report.append("   - Implement proper SSL/TLS verification")
        report.append("   - Use strong encryption algorithms")
        report.append("")
        report.append("3. **Input Validation:**")
        report.append("   - Validate all user inputs")
        report.append("   - Use parameterized queries for database operations")
        report.append("   - Sanitize file paths and prevent path traversal")
        report.append("")
        report.append("4. **Dependency Management:**")
        report.append("   - Regularly update dependencies")
        report.append("   - Use dependency scanning tools")
        report.append("   - Pin dependency versions with hash verification")
        report.append("")
        report.append("5. **Access Control:**")
        report.append("   - Implement proper file permissions")
        report.append("   - Use principle of least privilege")
        report.append("   - Regular security audits")
        report.append("")
        
        return "\n".join(report)
    
    def save_report(self, report: str, filename: str = "security_audit_report.md"):
        """Save security report to file."""
        report_path = self.project_root / filename
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"📄 Security report saved to {report_path}")


def main():
    """Main entry point for the security audit script."""
    parser = argparse.ArgumentParser(
        description="CouchPotato Security Audit Tool"
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Run comprehensive security scan"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply automatic security fixes"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate security report"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)"
    )
    
    args = parser.parse_args()
    
    if not any([args.scan, args.fix, args.report]):
        parser.error("Must specify one of --scan, --fix, or --report")
    
    auditor = SecurityAuditor(args.project_root)
    
    if args.scan or args.report:
        findings = auditor.scan_codebase()
        
        if args.scan:
            print("\n🚨 Security Scan Results:")
            for severity in ["critical", "high", "medium", "low", "info"]:
                count = len(findings[severity])
                if count > 0:
                    print(f"  {severity.title()}: {count} issues")
            
            total = sum(len(findings_list) for findings_list in findings.values())
            print(f"\nTotal issues found: {total}")
        
        if args.report:
            report = auditor.generate_security_report(findings)
            auditor.save_report(report)
    
    if args.fix:
        fixes = auditor.apply_automatic_fixes()
        print("\n🔧 Automatic Fixes Applied:")
        for fix_type, count in fixes.items():
            if count > 0:
                print(f"  {fix_type.replace('_', ' ').title()}: {count} fixes")


if __name__ == "__main__":
    main()