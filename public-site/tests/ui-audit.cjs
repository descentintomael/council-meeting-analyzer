// UI Audit Script - captures screenshots and analyzes page structure
const { chromium } = require('@playwright/test');
const fs = require('fs');

const BASE_URL = 'http://localhost:4321/council-meeting-analyzer';

async function auditUI() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });
  const page = await context.newPage();

  const audit = {
    homepage: {},
    meetingPage: {},
    membersPage: {},
  };

  // ===== HOMEPAGE AUDIT =====
  console.log('\n=== HOMEPAGE AUDIT ===\n');
  await page.goto(BASE_URL);
  await page.waitForLoadState('networkidle');

  // Screenshot
  await page.screenshot({ path: '/tmp/ui-audit-homepage.png', fullPage: true });
  console.log('Screenshot saved: /tmp/ui-audit-homepage.png');

  // Count elements
  audit.homepage.navLinks = await page.locator('header nav a').count();
  audit.homepage.badges = await page.locator('.badge').count();
  audit.homepage.buttons = await page.locator('.btn').count();
  audit.homepage.cards = await page.locator('.card').count();
  audit.homepage.headings = await page.locator('h1, h2, h3').count();

  // Hero section analysis
  const heroText = await page.locator('section.bg-base-200').first().textContent();
  audit.homepage.heroWordCount = heroText.split(/\s+/).length;

  // Latest meeting section
  audit.homepage.hasLatestMeetingSection = await page.locator('text=Latest Meeting').count() > 0;

  // Filter bar
  audit.homepage.filterButtons = await page.locator('.btn:has-text("City Council"), .btn:has-text("All")').count();

  // Meeting cards analysis
  const firstCard = page.locator('.card').first();
  audit.homepage.cardBadgeCount = await firstCard.locator('.badge').count();
  audit.homepage.cardTextElements = await firstCard.locator('span, p, div').count();

  console.log('Homepage stats:', JSON.stringify(audit.homepage, null, 2));

  // ===== MEETING PAGE AUDIT =====
  console.log('\n=== MEETING PAGE AUDIT ===\n');
  await page.locator('a[href*="/meetings/"]').first().click();
  await page.waitForLoadState('networkidle');

  await page.screenshot({ path: '/tmp/ui-audit-meeting.png', fullPage: true });
  console.log('Screenshot saved: /tmp/ui-audit-meeting.png');

  audit.meetingPage.badges = await page.locator('.badge').count();
  audit.meetingPage.buttons = await page.locator('.btn').count();
  audit.meetingPage.headings = await page.locator('h1, h2, h3').count();
  audit.meetingPage.sections = await page.locator('section').count();
  audit.meetingPage.sidebarItems = await page.locator('aside > div').count();

  // Header complexity
  const header = page.locator('header').first();
  audit.meetingPage.headerElements = await header.locator('span, a, div').count();

  // Sidebar info redundancy check
  const sidebarText = await page.locator('aside').textContent();
  const mainText = await page.locator('main').textContent();

  // Check for duplicated info patterns
  audit.meetingPage.dateInSidebar = sidebarText.includes('Date');
  audit.meetingPage.typeInSidebar = sidebarText.includes('Type');
  audit.meetingPage.votesInSidebar = sidebarText.includes('Votes');

  // Button redundancy
  audit.meetingPage.watchVideoButtons = await page.locator('text=Watch Video').count();
  audit.meetingPage.watchRecordingButtons = await page.locator('text=Open in Granicus').count();

  console.log('Meeting page stats:', JSON.stringify(audit.meetingPage, null, 2));

  // ===== MEMBERS PAGE AUDIT =====
  console.log('\n=== MEMBERS PAGE AUDIT ===\n');
  await page.goto(`${BASE_URL}/members`);
  await page.waitForLoadState('networkidle');

  await page.screenshot({ path: '/tmp/ui-audit-members.png', fullPage: true });
  console.log('Screenshot saved: /tmp/ui-audit-members.png');

  audit.membersPage.cards = await page.locator('.card').count();
  audit.membersPage.badges = await page.locator('.badge').count();

  console.log('Members page stats:', JSON.stringify(audit.membersPage, null, 2));

  // ===== MOBILE VIEW AUDIT =====
  console.log('\n=== MOBILE VIEW AUDIT ===\n');
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(BASE_URL);
  await page.waitForLoadState('networkidle');

  await page.screenshot({ path: '/tmp/ui-audit-mobile.png', fullPage: true });
  console.log('Screenshot saved: /tmp/ui-audit-mobile.png');

  audit.mobile = {};
  audit.mobile.visibleNavLinks = await page.locator('header nav a:visible').count();
  audit.mobile.hasHamburger = await page.locator('header .dropdown').count() > 0;

  console.log('Mobile stats:', JSON.stringify(audit.mobile, null, 2));

  // ===== VISUAL ANALYSIS =====
  console.log('\n=== ANALYSIS SUMMARY ===\n');

  console.log('POTENTIAL ISSUES FOUND:');

  if (audit.homepage.badges > 30) {
    console.log(`- HIGH BADGE COUNT: ${audit.homepage.badges} badges on homepage (visual noise)`);
  }

  if (audit.meetingPage.watchVideoButtons + audit.meetingPage.watchRecordingButtons > 2) {
    console.log(`- DUPLICATE VIDEO LINKS: ${audit.meetingPage.watchVideoButtons} "Watch Video" + ${audit.meetingPage.watchRecordingButtons} "Open in Granicus"`);
  }

  if (audit.meetingPage.sidebarItems > 4) {
    console.log(`- SIDEBAR COMPLEXITY: ${audit.meetingPage.sidebarItems} sidebar sections`);
  }

  if (audit.homepage.heroWordCount > 50) {
    console.log(`- HERO TEXT LENGTH: ${audit.homepage.heroWordCount} words in hero section`);
  }

  if (audit.homepage.cardBadgeCount > 5) {
    console.log(`- CARD BADGE OVERLOAD: ${audit.homepage.cardBadgeCount} badges per card`);
  }

  await browser.close();

  // Write full audit
  fs.writeFileSync('/tmp/ui-audit-results.json', JSON.stringify(audit, null, 2));
  console.log('\nFull audit saved to /tmp/ui-audit-results.json');
}

auditUI().catch(console.error);
