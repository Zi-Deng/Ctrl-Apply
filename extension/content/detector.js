/**
 * ATS platform detection from URL patterns.
 * Injected into job application pages as a content script.
 */

/* exported detectATS */

function detectATS(url) {
  url = url || window.location.href;
  const u = url.toLowerCase();

  if (u.includes("boards.greenhouse.io") || u.includes("job-boards.greenhouse.io")) {
    return "greenhouse";
  }
  if (u.includes("myworkdayjobs.com") || u.includes("myworkdaysite.com")) {
    return "workday";
  }
  if (u.includes("lever.co") || u.includes("jobs.lever.co")) {
    return "lever";
  }
  if (u.includes("icims.com")) {
    return "icims";
  }
  if (u.includes("smartrecruiters.com")) {
    return "smartrecruiters";
  }
  if (u.includes("ashbyhq.com")) {
    return "ashby";
  }
  if (u.includes("bamboohr.com")) {
    return "bamboohr";
  }
  if (u.includes("jobvite.com")) {
    return "jobvite";
  }
  if (u.includes("taleo.net")) {
    return "taleo";
  }
  if (u.includes("breezy.hr")) {
    return "breezy";
  }
  if (u.includes("recruitee.com")) {
    return "recruitee";
  }

  return "generic";
}
