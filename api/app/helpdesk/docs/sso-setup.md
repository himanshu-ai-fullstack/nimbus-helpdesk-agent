# Set up SAML single sign-on (Business plan)

SAML SSO is available on the Business plan. Nimbus supports Okta, Microsoft Entra ID, Google Workspace, and any SAML 2.0 identity provider.

1. Go to **Settings > Security > SSO** and choose **Configure SAML**.
2. Copy the ACS URL and Entity ID into your identity provider.
3. Paste your provider's metadata URL into Nimbus and click **Test connection**.
4. Turn on **Enforce SSO** once the test succeeds. Members then sign in through your provider.

If the test fails with "audience mismatch", the Entity ID in your provider does not match the one Nimbus shows. Keep one owner account outside SSO enforcement so you never lock yourself out.
