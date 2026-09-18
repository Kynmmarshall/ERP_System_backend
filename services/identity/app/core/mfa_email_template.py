"""HTML body for the admin sign-in code email.

Email clients are not browsers: no flexbox/grid, no <style> blocks in Gmail,
no external stylesheets. Hence table-based layout with fully inline styles, a
fixed 600px content width, and - importantly - a design that still reads
correctly when the logo is blocked, since most clients block remote images by
default. The wordmark is therefore real text, never an image.
"""
from app.core.config import settings

# Mirrors src/styles/tokens.css. Hard-coded hex because email clients do not
# support CSS custom properties.
_BG = "#0E1116"
_SURFACE = "#151A21"
_BORDER = "#2B313B"
_TEXT = "#F2F5F8"
_MUTED = "#9AA4B2"
_PRIMARY = "#14AFD6"
_FONT = "'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def render_mfa_html(*, to_name: str, code: str, minutes: int) -> str:
    logo_url = settings.mfa_email_logo_url
    spaced_code = " ".join(code)
    # A remote <img> that is blocked OR fails to resolve renders as a broken
    # image icon in several clients, so the default mark is drawn with table
    # cells and always renders. The real logo is opt-in, for when the URL is
    # confirmed publicly reachable.
    if logo_url:
        brand_mark = (
            f'<img src="{logo_url}" width="36" height="36" alt=""'
            f' style="display:block;border:0;outline:none;text-decoration:none;'
            f'width:36px;height:36px;border-radius:6px;" />'
        )
    else:
        brand_mark = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"'
            f' style="width:36px;height:36px;background-color:{_PRIMARY};border-radius:6px;">'
            f'<tr><td align="center" valign="middle"'
            f' style="font-family:{_FONT};font-size:14px;font-weight:700;color:{_BG};'
            f'line-height:36px;height:36px;">IU</td></tr></table>'
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<meta name="color-scheme" content="dark light" />
<title>Your sign-in code</title>
</head>
<body style="margin:0;padding:0;background-color:{_BG};">
<div style="display:none;font-size:1px;color:{_BG};line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
Your ICT University ERP sign-in code is {code}. It expires in {minutes} minutes.
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       style="background-color:{_BG};padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
             style="width:100%;max-width:600px;background-color:{_SURFACE};
                    border:1px solid {_BORDER};border-radius:8px;">

        <tr>
          <td style="padding:24px 32px;border-bottom:1px solid {_BORDER};">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td style="padding-right:12px;">{brand_mark}</td>
                <td style="font-family:{_FONT};font-size:15px;font-weight:600;color:{_TEXT};letter-spacing:0.02em;">
                  ICT University <span style="color:{_MUTED};font-weight:400;">ERP</span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 32px 0 32px;font-family:{_FONT};">
            <h1 style="margin:0 0 8px 0;font-size:20px;line-height:1.3;font-weight:600;color:{_TEXT};">
              Your sign-in code
            </h1>
            <p style="margin:0;font-size:14px;line-height:1.6;color:{_MUTED};">
              Hello {to_name}, use this code to finish signing in to your administrator account.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:24px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background-color:{_BG};border:1px solid {_BORDER};border-radius:6px;">
              <tr>
                <td align="center" style="padding:24px 16px;font-family:{_FONT};">
                  <div style="font-size:11px;font-weight:600;letter-spacing:0.18em;
                              text-transform:uppercase;color:{_MUTED};padding-bottom:12px;">
                    Verification code
                  </div>
                  <div style="font-family:Consolas,'Courier New',monospace;font-size:32px;
                              font-weight:700;letter-spacing:0.26em;color:{_PRIMARY};line-height:1.2;">
                    {spaced_code}
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:0 32px;font-family:{_FONT};">
            <p style="margin:0;font-size:14px;line-height:1.6;color:{_MUTED};">
              This code expires in <span style="color:{_TEXT};font-weight:600;">{minutes} minutes</span>
              and can only be used once.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:20px 32px 32px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                   style="background-color:{_BG};border-left:3px solid {_PRIMARY};border-radius:4px;">
              <tr>
                <td style="padding:14px 16px;font-family:{_FONT};font-size:13px;line-height:1.6;color:{_MUTED};">
                  Didn't try to sign in? Someone may know your password.
                  <span style="color:{_TEXT};">Change it immediately</span> and tell your administrator.
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:16px 32px;border-top:1px solid {_BORDER};font-family:{_FONT};
                     font-size:12px;line-height:1.6;color:{_MUTED};">
            Automated message - replies are not monitored. We will never ask you for this code.
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def render_mfa_text(*, to_name: str, code: str, minutes: int) -> str:
    """Plain-text alternative: some clients render only this, and omitting it
    hurts deliverability."""
    return (
        f"Hello {to_name},\n\n"
        f"Your ICT University ERP sign-in code is: {code}\n\n"
        f"It expires in {minutes} minutes and can only be used once.\n\n"
        "If you did not try to sign in, change your password immediately and tell\n"
        "your administrator. We will never ask you for this code.\n\n"
        "Automated message - replies are not monitored.\n"
    )
