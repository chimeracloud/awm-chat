"""AWM firm reference injected into every agent's system prompt.

This module supplies two things to chat.py:

- ``AWM_CONTEXT`` — a curated briefing on Ascot Wealth Management,
  distilled from ascotwm.com. Injected into every system prompt so the
  agent answers AWM-specific questions accurately without having to
  fetch the site each turn.
- ``AWM_GUIDANCE`` — short instructions on when to draw on the static
  context vs. reach for web search.

Both are provider-neutral: the same text is sent to Claude, OpenAI and
Gemini. Each vendor's web-search tool is declared by its own adapter in
``providers/`` rather than here, because the three tool specs differ.

ascotwm.com is a JavaScript-rendered single-page application, so web
fetching will not retrieve useful content from its sub-pages. That is why
the firm reference is baked in as static context here rather than fetched
on demand. Refresh ``AWM_CONTEXT`` periodically (or whenever ascotwm.com
is materially updated).

Last refreshed from ascotwm.com on 2026-05-21.
"""

AWM_CONTEXT = """## Ascot Wealth Management — firm reference

Ascot Wealth Management Ltd ("AWM") is an FCA-regulated, independent
financial advisory firm in the UK. AWM has operated from Ascot since
1994 and has been an independent advisory firm since being founded in
2010 by Mark Insley. The firm is family-run and emphasises plain
English, transparent fees, and whole-of-market independent advice
(not tied to any provider).

Website: https://ascotwm.com
Regulator: Authorised and regulated by the Financial Conduct Authority (FCA).

### Offices and contact

Primary office (Sunningdale):
- Address: Scotch Corner, London Road, Sunningdale, Berkshire, SL5 0ER
- Phone: 01344 851 250
- Email: enquiries@ascotwm.com
- Hours: Mon–Thu 08:00–17:00, Fri 09:00–16:00

Ascot office:
- Address: 19–21 High Street, Ascot, Berkshire, SL5 7JW
- Phone: 01344 625 625
- Email: info@ascotwm.com
- Hours: Mon–Fri 09:00–17:30

### Scale and credentials

- £500M+ assets under management (as stated on the website)
- 1,195+ verified VouchedFor reviews, 4.8 / 5 average rating
- Four rated advisers; combined team experience 30+ years
- Stated as "award-winning" for client service and outcomes

### Services

AWM offers six core services. All are delivered with transparent,
upfront fees explained in pounds before any work begins.

1. **Investment Management** — Globally diversified portfolios (shares,
   bonds, specialist holdings) tailored to a client's risk profile;
   ongoing rebalancing, tax-efficient investing, access to
   institutional-grade investments, regular performance reviews.
2. **Retirement Planning** — Pension transfer analysis, income drawdown
   strategies, state-pension optimisation, retirement cash-flow
   modelling, legacy planning. The aim is to show clearly how much
   income pensions and savings can pay in retirement and for how long.
3. **Protection Planning** — Whole-of-market search across life
   assurance, family income benefit, critical illness protection,
   income replacement cover, and trust arrangements. Keeps the
   mortgage paid and the family looked after if the client dies or
   cannot work.
4. **Mortgage Advisory** — Whole-of-market access, first-time-buyer
   support, remortgage savings analysis, buy-to-let, self-employed
   cases. Aim is lowest total cost over the period the client
   actually plans to hold the mortgage.
5. **Financial Planning** — A written, year-by-year plan covering
   income and asset mapping, goal-based forecasting, risk-appetite
   assessment, liability management, and comprehensive wealth
   strategies, using modern cash-flow software.
6. **Corporate Services** — Workplace pension schemes, key person
   insurance, share-option schemes, business succession planning,
   director benefits, employee financial wellness programmes.
   Scheme charges negotiated down on the business's behalf.

### Investment philosophy

AWM describes its investment approach as combining rigorous research,
disciplined strategy and personalised portfolio construction. Four
stated pillars:

- **Goal-driven strategy** — every investment decision aligned with the
  client's specific objectives and timeline.
- **Risk-aware approach** — comprehensive risk assessment ensures the
  portfolio matches the client's risk tolerance.
- **Long-term focus** — wealth built through disciplined long-term
  strategies.
- **Data-driven decisions** — market research and analytics inform
  investment choices.

Process: Research & Analysis → Portfolio Construction → Ongoing Management.

Standard portfolio models illustrated on the site:

- Conservative — low risk; 70 % bonds / 30 % equities; expected 4–6 % p.a.
- Moderate — medium risk; 50 % bonds / 50 % equities; expected 6–8 % p.a.
- Aggressive — high risk; 20 % bonds / 80 % equities; expected 8–12 % p.a.

### Client process

1. **Free initial call** — 20-minute phone call; no obligation, no
   sales pitch.
2. **Discovery meeting** — free, in person or video. Income, assets,
   family situation, concerns.
3. **Personal plan** — clear recommendations in plain English; options
   walked through; proceeds only when the client is comfortable.
4. **Ongoing relationship** — at least annual reviews, more often if
   the client's life changes. Direct access to the adviser, not a call
   centre.

### Fees

Stated as clear, competitive, agreed upfront, with no hidden charges:

- Initial consultation — free, no obligation.
- Advice and implementation — fixed fee agreed upfront, in writing.
- Ongoing management — typically 0.5 % – 1 % per year of assets under
  management.

### Team (as published on the homepage)

- **Mark Insley** — Founder & Director. Strategic leadership,
  investment management, client relations. ~696 VouchedFor reviews,
  4.8 average. Founded AWM in 2010.
- **Claire Calder** — Wealth Manager. Protection planning, investment
  advice, estate planning. ~108 reviews, 4.8.
- **Catriona McCarron** — Wealth Manager. ~351 reviews, 4.8. Stated
  motto: "Acting with trust and integrity to meet your financial
  objectives."
- A fourth rated adviser is also on the team — refer the user to
  https://ascotwm.com/staff for the current full team.

### What AWM emphasises (mirror this tone)

- Family-run, in Ascot for over 30 years.
- Independent — not tied to any product or commission.
- Plain English; no jargon; honest answers.
- Transparent fees — in pounds, in writing, before any work begins.
- Personal approach — one dedicated adviser who knows the full picture.
- Long-term relationships built on trust.

### Common questions (paraphrased from https://ascotwm.com/faq)

- **What is wealth management?** A holistic financial advisory service
  combining investment management, financial planning, tax advice,
  retirement planning and estate planning.
- **Do I need to be wealthy?** No — AWM works with clients at various
  stages, from growth to retirement to family protection. A free
  initial consultation is the right first step.
- **Adviser vs wealth manager?** A financial adviser typically focuses
  on specific products (pensions, investments); a wealth manager takes
  a holistic view of the client's entire financial life.
- **How to pick an adviser?** FCA regulation, relevant qualifications
  (e.g. Chartered Financial Planner), strong client reviews,
  transparent fees.
- **ISAs?** Tax-efficient wrapper, up to £20,000 per year. Cash,
  Stocks & Shares, or Lifetime ISA — AWM helps pick the right type for
  the goal.
- **Inheritance tax?** Several legitimate strategies — gifts, trusts,
  qualifying investments, reliefs and exemptions. AWM builds a tailored
  estate-planning strategy.
- **Pension options at retirement?** Drawdown (flexible access),
  annuity (guaranteed income), or a mix. Depends on circumstances,
  health, risk tolerance, and income needs.
- **Review cadence?** At least annual, more often when circumstances
  change. Clients can contact their adviser at any time.

### Useful URLs on ascotwm.com

- Home: https://ascotwm.com/
- Services overview: https://ascotwm.com/services
- Investment Management: https://ascotwm.com/services/investment-management
- Retirement Planning: https://ascotwm.com/services/retirement-planning
- Protection Planning: https://ascotwm.com/services/protection-planning
- Mortgage Advisory: https://ascotwm.com/services/mortgage-advisory
- Financial Planning: https://ascotwm.com/services/financial-planning
- Corporate Services: https://ascotwm.com/services/corporate-services
- Investment approach: https://ascotwm.com/investment-approach
- About / our story: https://ascotwm.com/about
- Team: https://ascotwm.com/staff
- Testimonials: https://ascotwm.com/testimonials
- FAQ: https://ascotwm.com/faq
- Blog: https://ascotwm.com/blog
- Insights / research: https://ascotwm.com/insights
- Market updates: https://ascotwm.com/market-updates
- Contact: https://ascotwm.com/contact
- Privacy policy: https://ascotwm.com/privacy-policy
- Cookie policy: https://ascotwm.com/cookies-policy

### Social

- LinkedIn: https://www.linkedin.com/company/ascot-wealth-management/
- YouTube: https://www.youtube.com/channel/UCU1jKABZwwBsLmtBVye-Y7A
- Facebook: https://www.facebook.com/ascotwealth/
"""


AWM_GUIDANCE = """## Using the AWM context and the web tools

The AWM firm reference above is authoritative when answering questions
about AWM itself — its services, philosophy, team, locations, fees,
process and tone. Mirror AWM's plain-English, no-jargon,
transparent-fee style.

You also have access to a server-side web search tool. Use it for
current market information, news, regulatory or tax updates, comparison
facts, or general internet research that isn't AWM-specific. For
AWM-specific questions rely on the firm reference above and link the
user to the relevant ascotwm.com page.

When using web search:

- Cite the source URL when stating a fact that came from the web.
- Verify regulatory, tax or compliance claims against an authoritative
  source (FCA, HMRC, gov.uk) before stating them as fact.
- Stay within AWM's plain-English style. Translate jargon for the user.

If the user asks something AWM-specific (e.g. "what services do we
offer", "who's on the team", "how much do we charge"), draw from the
firm reference above without searching — it is the authoritative
source.
"""
