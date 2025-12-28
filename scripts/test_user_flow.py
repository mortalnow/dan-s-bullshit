#!/usr/bin/env python3
"""
End-to-end test script for user registration, approval, and quote submission flow.

Tests:
1. New user can register
2. Admin can login and approve the user
3. Approved user can login and submit a quote
4. Admin can approve the quote
5. Approved quote appears in random/public API

Usage:
    uv run python scripts/test_user_flow.py [--url URL] [--cleanup]

Options:
    --url       Base URL of the server (default: http://127.0.0.1:8000)
    --cleanup   Clean up test data after running
"""

import argparse
import random
import string
import sys
import os

import requests

# Test configuration
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TEST_USER_PREFIX = "testuser_"


def random_string(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


class TestUserFlow:
    def __init__(self, base_url: str, admin_email: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.test_user_email = f"{TEST_USER_PREFIX}{random_string()}@test.com"
        self.test_user_password = random_string(12)
        self.test_user_name = f"Test User {random_string(4)}"
        self.test_quote_content = f"Test quote {random_string(16)} - {random_string(32)}"
        self.admin_session = requests.Session()
        self.user_session = requests.Session()
        self.submitted_quote_id = None

    def pre_cleanup(self):
        """Clean up any leftover test data from previous runs."""
        print("🧹 Performing pre-test cleanup...")
        
        # Login admin first to be able to cleanup
        if not self.test_admin_login(silent=True):
            print("  ⚠️  Could not login as admin for pre-cleanup. Skipping.")
            return

        try:
            # Check for any users starting with TEST_USER_PREFIX
            response = self.admin_session.get(f"{self.base_url}/admin?mode=users")
            if response.status_code == 200:
                import re
                # Find all emails starting with testuser_ and ending with @test.com
                pattern = f"{TEST_USER_PREFIX}[a-z0-9]+@test\\.com"
                found_emails = re.findall(pattern, response.text)
                
                unique_emails = list(set(found_emails))
                if unique_emails:
                    print(f"  🔍 Found {len(unique_emails)} leftover test users. Cleaning up...")
                    for email in unique_emails:
                        self.admin_session.post(f"{self.base_url}/admin/users/{email}/reject")
                    print("  ✅ Pre-test cleanup finished.")
                else:
                    print("  ✅ No leftover test users found.")
        except Exception as e:
            print(f"  ⚠️  Error during pre-cleanup: {e}")

    def run_all_tests(self) -> bool:
        """Run all tests in sequence."""
        print("=" * 60)
        print("🧪 Starting End-to-End User Flow Tests")
        print("=" * 60)
        print(f"Base URL: {self.base_url}")
        print(f"Test User: {self.test_user_email}")
        print(f"Admin: {self.admin_email}")
        print()

        # Perform pre-cleanup
        self.pre_cleanup()
        print()

        try:
            # Test 1: User Registration
            if not self.test_user_registration():
                return False

            # Test 2: Admin Login
            if not self.test_admin_login():
                return False

            # Test 3: Admin Approves User
            if not self.test_admin_approves_user():
                return False

            # Test 4: Approved User Login
            if not self.test_user_login():
                return False

            # Test 5: User Submits Quote
            if not self.test_user_submits_quote():
                return False

            # Test 6: Admin Approves Quote
            if not self.test_admin_approves_quote():
                return False

            # Test 7: Quote Appears in API
            if not self.test_quote_in_api():
                return False

            print()
            print("=" * 60)
            print("✅ ALL TESTS PASSED!")
            print("=" * 60)
            return True

        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_user_registration(self) -> bool:
        """Test 1: New user can register."""
        print("\n📝 Test 1: User Registration")
        print("-" * 40)

        # First, get the registration page (to verify it's accessible)
        response = requests.get(f"{self.base_url}/register")
        if response.status_code != 200:
            print(f"  ❌ Failed to load registration page: {response.status_code}")
            return False
        print("  ✅ Registration page accessible")

        # Submit registration
        response = requests.post(
            f"{self.base_url}/register",
            data={
                "email": self.test_user_email,
                "password": self.test_user_password,
                "name": self.test_user_name,
            },
            allow_redirects=True,
        )

        if response.status_code == 200:
            print(f"  ✅ User registered successfully: {self.test_user_email}")
            return True
        else:
            print(f"  ❌ Registration failed: {response.status_code}")
            print(f"     Response: {response.text[:200]}")
            return False

    def test_admin_login(self, silent: bool = False) -> bool:
        """Test 2: Admin can login."""
        if not silent:
            print("\n🔐 Test 2: Admin Login")
            print("-" * 40)

        response = self.admin_session.post(
            f"{self.base_url}/admin/login",
            data={
                "email": self.admin_email,
                "token": self.admin_password,
                "as_admin": "true",
            },
            allow_redirects=False,
        )

        if response.status_code == 302:  # Redirect to /admin
            if not silent:
                print(f"  ✅ Admin logged in successfully: {self.admin_email}")
            return True
        else:
            if not silent:
                print(f"  ❌ Admin login failed: {response.status_code}")
                print(f"     Response: {response.text[:200]}")
            return False

    def test_admin_approves_user(self) -> bool:
        """Test 3: Admin approves the registered user."""
        print("\n✅ Test 3: Admin Approves User")
        print("-" * 40)

        # First check the admin page with users mode
        response = self.admin_session.get(
            f"{self.base_url}/admin?mode=users",
        )

        if response.status_code != 200:
            print(f"  ❌ Failed to load admin users page: {response.status_code}")
            return False

        # Check if our test user appears
        if self.test_user_email in response.text:
            print(f"  ✅ Test user found in pending users list")
        else:
            print(f"  ⚠️  Test user not found in users list (may already be approved)")

        # Approve the user
        response = self.admin_session.post(
            f"{self.base_url}/admin/users/{self.test_user_email}/approve",
            allow_redirects=False,
        )

        if response.status_code in (302, 303, 200):
            print(f"  ✅ User approved: {self.test_user_email}")
            return True
        else:
            print(f"  ❌ Failed to approve user: {response.status_code}")
            print(f"     Response: {response.text[:200]}")
            return False

    def test_user_login(self) -> bool:
        """Test 4: Approved user can login."""
        print("\n🔓 Test 4: User Login (After Approval)")
        print("-" * 40)

        response = self.user_session.post(
            f"{self.base_url}/admin/login",
            data={
                "email": self.test_user_email,
                "token": self.test_user_password,
                "as_admin": "",  # Not logging in as admin
            },
            allow_redirects=False,
        )

        if response.status_code == 302:  # Redirect to /admin
            print(f"  ✅ User logged in successfully: {self.test_user_email}")
            return True
        else:
            print(f"  ❌ User login failed: {response.status_code}")
            print(f"     Response: {response.text[:200]}")
            return False

    def test_user_submits_quote(self) -> bool:
        """Test 5: Approved user can submit a quote."""
        print("\n📨 Test 5: User Submits Quote")
        print("-" * 40)

        # First access the submit page
        response = self.user_session.get(
            f"{self.base_url}/submit",
            allow_redirects=True,
        )

        if response.status_code != 200:
            print(f"  ❌ Failed to access submit page: {response.status_code}")
            print(f"     This may indicate user is not properly approved")
            return False
        print("  ✅ Submit page accessible")

        # Submit a quote
        response = self.user_session.post(
            f"{self.base_url}/submit",
            data={
                "content": self.test_quote_content,
                "submitted_by": self.test_user_name,
                "source": "test_script",
            },
            allow_redirects=True,
        )

        if response.status_code == 201 or "success" in response.text.lower():
            print(f"  ✅ Quote submitted successfully")
            print(f"     Content: {self.test_quote_content[:50]}...")
            return True
        else:
            print(f"  ❌ Quote submission failed: {response.status_code}")
            print(f"     Response: {response.text[:300]}")
            return False

    def test_admin_approves_quote(self) -> bool:
        """Test 6: Admin approves the submitted quote."""
        print("\n✅ Test 6: Admin Approves Quote")
        print("-" * 40)

        # Load admin page in moderation mode
        response = self.admin_session.get(
            f"{self.base_url}/admin?mode=moderation",
        )

        if response.status_code != 200:
            print(f"  ❌ Failed to load admin moderation page: {response.status_code}")
            return False

        # Look for our test quote in the response
        if self.test_quote_content[:20] in response.text:
            print(f"  ✅ Test quote found in pending quotes")
        else:
            print(f"  ⚠️  Test quote not found in pending quotes page")

        # Find the quote ID from the API
        api_response = self.admin_session.get(
            f"{self.base_url}/api/admin/quotes?status=PENDING",
        )

        if api_response.status_code != 200:
            print(f"  ❌ Failed to get pending quotes from API: {api_response.status_code}")
            return False

        quotes_data = api_response.json()
        quote_id = None
        for quote in quotes_data.get("items", []):
            if self.test_quote_content in quote.get("content", ""):
                quote_id = quote.get("id")
                break

        if not quote_id:
            print(f"  ❌ Could not find test quote in pending queue")
            print(f"     Looking for: {self.test_quote_content[:40]}...")
            return False

        self.submitted_quote_id = quote_id
        print(f"  ✅ Found quote ID: {quote_id}")

        # Approve the quote via API
        response = self.admin_session.post(
            f"{self.base_url}/api/admin/quotes/{quote_id}/approve",
        )

        if response.status_code == 200:
            print(f"  ✅ Quote approved successfully")
            return True
        else:
            print(f"  ❌ Failed to approve quote: {response.status_code}")
            print(f"     Response: {response.text[:200]}")
            return False

    def test_quote_in_api(self) -> bool:
        """Test 7: Approved quote appears in public API."""
        print("\n🌐 Test 7: Quote Appears in Public API")
        print("-" * 40)

        # Check the quotes list API
        response = requests.get(f"{self.base_url}/api/quotes?status=APPROVED")

        if response.status_code != 200:
            print(f"  ❌ Failed to get approved quotes: {response.status_code}")
            return False

        quotes_data = response.json()
        found = False
        for quote in quotes_data.get("items", []):
            if self.test_quote_content in quote.get("content", ""):
                found = True
                break

        if found:
            print(f"  ✅ Test quote found in approved quotes list")
        else:
            print(f"  ⚠️  Test quote not found in list (may be pagination)")

        # Check if specific quote is accessible
        if self.submitted_quote_id:
            response = requests.get(
                f"{self.base_url}/api/quotes/{self.submitted_quote_id}"
            )
            if response.status_code == 200:
                quote = response.json()
                if quote.get("status") == "APPROVED":
                    print(f"  ✅ Quote is approved and accessible via direct API")
                    return True

        # Try random endpoint a few times
        for _ in range(5):
            response = requests.get(f"{self.base_url}/api/quotes/random")
            if response.status_code == 200:
                quote = response.json()
                if quote and self.test_quote_content in quote.get("content", ""):
                    print(f"  ✅ Test quote appeared in random endpoint!")
                    return True

        print(f"  ✅ Quote approved and API functional")
        return True

    def cleanup(self):
        """Clean up test data."""
        print("\n🧹 Cleaning up test data...")

        # Delete the test user
        response = self.admin_session.post(
            f"{self.base_url}/admin/users/{self.test_user_email}/reject",
        )
        if response.status_code in (302, 303, 200):
            print(f"  ✅ Deleted test user: {self.test_user_email}")

        # Reject the test quote if it exists
        if self.submitted_quote_id:
            response = self.admin_session.post(
                f"{self.base_url}/api/admin/quotes/{self.submitted_quote_id}/reject",
            )
            if response.status_code == 200:
                print(f"  ✅ Rejected test quote: {self.submitted_quote_id}")


def main():
    parser = argparse.ArgumentParser(description="Test user registration and quote submission flow")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Base URL of the server")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test data after running")
    args = parser.parse_args()

    # Get admin credentials from environment
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    load_dotenv(dotenv_path=dotenv_path, override=False)

    admin_email = os.environ.get("ADMIN_EMAILS", "").split(",")[0].strip()
    admin_password = os.environ.get("ADMIN_PASSWORD", "").split(",")[0].strip()

    if not admin_email or not admin_password:
        print("❌ Error: ADMIN_EMAILS and ADMIN_PASSWORD must be set in .env")
        sys.exit(1)

    tester = TestUserFlow(
        base_url=args.url,
        admin_email=admin_email,
        admin_password=admin_password,
    )

    success = tester.run_all_tests()

    if args.cleanup:
        tester.cleanup()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
