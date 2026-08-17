// Automated check of the Globus voice-agent widget.
// Logs in via the dev OTP flow, grants mic permission, taps the orb,
// and records console/network/screenshot evidence of whether the
// ElevenLabs Conversational AI agent actually connects.
//
// Usage: node test_voice_agent.js
// Env:   SITE (default http://localhost:8090)
//        LOGIN_EMAIL (default phase4-agent@example.test)

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const SITE = process.env.SITE || 'http://localhost:8090';
const LOGIN_EMAIL = process.env.LOGIN_EMAIL || 'phase4-agent@example.test';
const OUT_DIR = path.join(__dirname, 'report');
fs.mkdirSync(OUT_DIR, { recursive: true });

const report = {
  site: SITE,
  login_email: LOGIN_EMAIL,
  started_at: new Date().toISOString(),
  steps: [],
  console_messages: [],
  network: [],
  page_errors: [],
  agent_id_seen: null,
  verdict: null,
};

function step(name, detail) {
  console.log(`[step] ${name}${detail ? ' — ' + detail : ''}`);
  report.steps.push({ name, detail: detail || null, at: new Date().toISOString() });
}

function getOtpFromLogs(email) {
  // Reads the dev-fallback OTP that globus_auth.py prints to the
  // container's stdout when no email provider is configured.
  const raw = execSync('docker compose logs --no-color --tail=500 globus', {
    cwd: path.join(__dirname, '..', '..'),
    encoding: 'utf8',
  });
  const lines = raw.split('\n').filter((l) => l.includes('[globus-auth][DEV] OTP code for') && l.includes(email));
  if (lines.length === 0) return null;
  const last = lines[lines.length - 1];
  const m = last.match(/OTP code for [^:]+:\s*(\d{4,8})/);
  return m ? m[1] : null;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    permissions: ['microphone'],
    // Fake mic device so getUserMedia() succeeds under Chromium headless.
  });
  await context.grantPermissions(['microphone'], { origin: SITE });

  const page = await context.newPage();

  page.on('console', (msg) => {
    const entry = { type: msg.type(), text: msg.text() };
    report.console_messages.push(entry);
    console.log(`[console:${entry.type}] ${entry.text}`);
  });
  page.on('pageerror', (err) => {
    report.page_errors.push(String(err));
    console.log(`[pageerror] ${err}`);
  });
  page.on('requestfailed', (req) => {
    report.network.push({
      url: req.url(),
      method: req.method(),
      failure: req.failure() && req.failure().errorText,
    });
  });
  page.on('response', (res) => {
    const url = res.url();
    if (url.includes('elevenlabs') || url.includes('convai') || url.includes('/members/')) {
      report.network.push({ url, status: res.status() });
    }
  });

  try {
    step('request OTP', `POST /members/login for ${LOGIN_EMAIL}`);
    await page.goto(`${SITE}/members/login`, { waitUntil: 'domcontentloaded' });
    await page.fill('input[name="email"]', LOGIN_EMAIL);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('button[type="submit"], input[type="submit"]'),
    ]);
    step('after email submit, url', page.url());

    let onCodePage = await page.$('input[name="code"]') !== null;
    if (!onCodePage) {
      // Likely hit the per-hour rate limit from repeated test/debug runs.
      // Reuse the most recent OTP already issued to this email instead.
      step('email submit did not reach code page (rate-limited?) — reusing last issued OTP');
      await page.goto(`${SITE}/members/login/code?email=${encodeURIComponent(LOGIN_EMAIL)}`, { waitUntil: 'domcontentloaded' });
      onCodePage = await page.$('input[name="code"]') !== null;
      if (!onCodePage) throw new Error(`Cannot reach OTP entry page for ${LOGIN_EMAIL} (url=${page.url()})`);
    }

    // give the log line a moment to flush
    await page.waitForTimeout(500);
    const otp = getOtpFromLogs(LOGIN_EMAIL);
    if (!otp) throw new Error('Could not find dev OTP in container logs for ' + LOGIN_EMAIL);
    step('OTP retrieved from container logs', otp);

    step('submit OTP');
    const codeInput = await page.$('input[name="code"]');
    if (!codeInput) throw new Error(`OTP code input not found on ${page.url()}`);
    await codeInput.fill(otp);
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
      page.click('button[type="submit"], input[type="submit"]'),
    ]);
    step('logged in, url', page.url());
    const cookiesAfterLogin = await context.cookies();
    report.cookies_after_login = cookiesAfterLogin.map((c) => ({
      name: c.name, domain: c.domain, path: c.path, secure: c.secure, sameSite: c.sameSite,
    }));
    step('cookies after login', JSON.stringify(report.cookies_after_login));

    await page.goto(`${SITE}/members/globus`, { waitUntil: 'networkidle' });
    step('open voice page, resolved url', page.url());

    const agentId = await page.evaluate(() => window.GLOBUS_AGENT_ID || '');
    report.agent_id_seen = agentId;
    step('window.GLOBUS_AGENT_ID', agentId ? agentId : '(empty)');

    step('tap the orb');
    await page.click('#voice-orb');
    await page.waitForTimeout(6000); // let the SDK attempt to connect

    const status = await page.evaluate(() => document.getElementById('voice-status')?.textContent || '');
    const mode = await page.evaluate(() => window.GLOBUS_MODE || '');
    const errVisible = await page.evaluate(() => {
      const el = document.getElementById('voice-error');
      return el ? getComputedStyle(el).display !== 'none' : false;
    });
    const errText = await page.evaluate(() => document.getElementById('voice-error')?.textContent || '');

    report.final_status_text = status;
    report.final_mode = mode;
    report.error_banner_visible = errVisible;
    report.error_banner_text = errText;
    step('final widget status', `mode=${mode} text="${status}" errorVisible=${errVisible}`);

    await page.screenshot({ path: path.join(OUT_DIR, 'voice_widget_after_tap.png'), fullPage: true });
    step('screenshot saved', 'voice_widget_after_tap.png');

    if (!agentId) {
      report.verdict = 'FAIL: ELEVENLABS_AGENT_ID is not configured (window.GLOBUS_AGENT_ID is empty) — the widget cannot connect regardless of mic permission.';
    } else if (errVisible) {
      report.verdict = `FAIL: error banner shown after tapping the orb: "${errText}"`;
    } else if (mode === 'listening') {
      report.verdict = 'PASS: agent connected and entered listening mode.';
    } else {
      report.verdict = `INCONCLUSIVE: no error banner, but mode="${mode}" (expected "listening").`;
    }
  } catch (e) {
    report.verdict = `FAIL: exception during test — ${e.message}`;
    report.exception_stack = e.stack;
    try {
      await page.screenshot({ path: path.join(OUT_DIR, 'voice_widget_error.png'), fullPage: true });
    } catch (_) {}
  } finally {
    await browser.close();
  }

  report.finished_at = new Date().toISOString();
  fs.writeFileSync(path.join(OUT_DIR, 'report.json'), JSON.stringify(report, null, 2));

  const md = [
    `# Globus voice-agent Playwright report`,
    ``,
    `- Site: ${report.site}`,
    `- Login: ${report.login_email}`,
    `- Run: ${report.started_at} → ${report.finished_at}`,
    `- **Verdict: ${report.verdict}**`,
    `- window.GLOBUS_AGENT_ID: \`${report.agent_id_seen || '(empty)'}\``,
    `- Final widget mode: \`${report.final_mode}\``,
    `- Final status text: "${report.final_status_text}"`,
    `- Error banner visible: ${report.error_banner_visible} — "${report.error_banner_text}"`,
    ``,
    `## Steps`,
    ...report.steps.map((s) => `- ${s.at} — ${s.name}${s.detail ? ' — ' + s.detail : ''}`),
    ``,
    `## Console messages`,
    ...report.console_messages.map((c) => `- [${c.type}] ${c.text}`),
    ``,
    `## Page errors`,
    ...(report.page_errors.length ? report.page_errors.map((e) => `- ${e}`) : ['(none)']),
    ``,
    `## Relevant network activity`,
    ...(report.network.length ? report.network.map((n) => `- ${JSON.stringify(n)}`) : ['(none)']),
    ``,
    `## Screenshot`,
    `See report/voice_widget_after_tap.png (or voice_widget_error.png on failure)`,
    ``,
  ].join('\n');
  fs.writeFileSync(path.join(OUT_DIR, 'report.md'), md);

  console.log('\n=== VERDICT ===');
  console.log(report.verdict);
  console.log(`Report written to ${OUT_DIR}`);
})();
