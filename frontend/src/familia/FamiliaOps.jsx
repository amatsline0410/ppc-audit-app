import React, { useEffect, useRef, useState } from 'react'
import './familiaops.css'

// FamiliaOps agency landing — faithful React conversion of the provided HTML
// (content unchanged). Own route (/familiaops), CSS scoped under .familia and
// code-split with this page so it never touches the app's styles.

const LinkedInIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.063 2.063 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452z"/></svg>
)
const EmailIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
)
const ChevronIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="6 9 12 15 18 9"/></svg>
)

const FAQS = [
  ['What size brands do you work with?',
   'We work best with brands doing $30K–$3M/month on Amazon or Shopify. Below that, our fees don\'t make sense yet — we\'ll usually refer you to a self-serve tool. Above that, we scale into hybrid team + agency arrangements.'],
  ['Do you require a long-term contract?',
   'No. Every engagement is month-to-month after an initial 60-day ramp. If we\'re not earning the retainer, you leave. That constraint keeps us honest.'],
  ['What does "AI Automation" actually mean?',
   'We build workflow automations using n8n, Zapier, and Make — connecting your tools (Amazon, Shopify, Klaviyo, Slack, Airtable, etc.) so data moves and tasks trigger without a human in the loop. Where it earns its keep, we drop GPT or Claude API calls into the workflow (auto-tag support tickets, summarize daily reports, draft listing copy). We\'re not selling you a chatbot — we\'re selling you back your team\'s hours.'],
  ['Who actually does the work?',
   'A named member of the family owns your account end-to-end. No offshore hand-off, no junior rotating in and out. You get their Slack, their calendar, and their direct line. Because we\'re family-run, the person you meet on the audit call is the person you work with — for as long as we work together.'],
  ['What does pricing look like?',
   'Retainers start at $2.5K/month for Amazon or Shopify management, and $1.5K+ for AI Automation builds (scoped per workflow). We publish full pricing on the audit call — no discovery-call gatekeeping.'],
  ['Where are you based?',
   'Manila and Cebu, Philippines — the family\'s home base. We work with brands in the US, EU, UK, and APAC. The timezone flexibility is a feature, not a bug: your account gets attention during US off-hours.'],
  ['What happens on the audit call?',
   'You send read-only access to your account or store before the call. We spend 30 minutes walking through what we\'d fix in the first 30, 60, and 90 days — with dollar estimates where possible. You leave with a written summary. No pitch, no follow-up sequence unless you ask for one.'],
]

export default function FamiliaOps() {
  const [scrolled, setScrolled] = useState(false)
  const [openFaq, setOpenFaq] = useState(new Set())
  const [heroTab, setHeroTab] = useState(0)
  const [resultsTab, setResultsTab] = useState(0)
  const rootRef = useRef(null)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in')
          io.unobserve(entry.target)
        }
      })
    }, { threshold: 0.12 })
    rootRef.current?.querySelectorAll('.reveal').forEach(el => io.observe(el))
    return () => io.disconnect()
  }, [])

  const toggleFaq = (i) => setOpenFaq(s => {
    const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n
  })

  return (
    <div className="familia" ref={rootRef}>

      {/* TOP NAV */}
      <header className={`top-nav${scrolled ? ' scrolled' : ''}`}>
        <div className="top-nav__inner">
          <a href="#" className="brand">
            <span className="brand-mark">F</span>
            <span>FamiliaOps</span>
          </a>
          <nav className="nav-menu">
            <a href="#services">Services</a>
            <a href="#team">Team</a>
            <a href="#results">Work</a>
            <a href="#process">Process</a>
            <a href="#faq">FAQ</a>
            <a href="#book">Contact</a>
          </nav>
          <div className="nav-right">
            <a href="/login" className="btn-text">Log In</a>
            <a href="#book" className="btn-primary-pill">Get Audit</a>
            <button className="nav-toggle" aria-label="Menu">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* HERO */}
      <section className="hero">
        <div className="container">
          <div className="hero-grid">
            <div>
              <div className="hero-eyebrow">Family-run · Digital ops agency</div>
              <h1>
                <span className="accent">$48M+</span> IN CLIENT REVENUE, RUN BY ONE FAMILY.
              </h1>
              <p className="hero-sub">
                FamiliaOps is a family-owned digital services agency. We handle Amazon, Shopify, and AI automation for e-commerce brands — as one team, under one roof, accountable to one name.
              </p>
              <div className="hero-cta-row">
                <a href="#book" className="btn-primary">Book free audit</a>
                <a href="#services" className="btn-secondary-dark">See services</a>
              </div>
              <div className="hero-meta">
                <span>✓ 60+ brands scaled</span>
                <span>✓ 4.2x average ROAS lift</span>
                <span>✓ No lock-in contracts</span>
              </div>
            </div>

            {/* Scoreboard card */}
            <div className="hero-card">
              <div className="hero-card__tabs">
                {['Live wins', 'Top gainers', 'New'].map((t, i) => (
                  <button key={t} className={`hero-card__tab${heroTab === i ? ' active' : ''}`}
                    onClick={() => setHeroTab(i)}>{t}</button>
                ))}
              </div>
              <div className="brand-row">
                <div className="brand-row__name">
                  <div className="brand-avatar a1">PI</div>
                  <span>Pro Ice · Amazon</span>
                </div>
                <div className="brand-row__metric">$412K / mo</div>
                <div className="brand-row__change change-up">▲ 38.2%</div>
              </div>
              <div className="brand-row">
                <div className="brand-row__name">
                  <div className="brand-avatar a2">LF</div>
                  <span>Louis Foster · Shopify</span>
                </div>
                <div className="brand-row__metric">$186K / mo</div>
                <div className="brand-row__change change-up">▲ 22.7%</div>
              </div>
              <div className="brand-row">
                <div className="brand-row__name">
                  <div className="brand-avatar a3">ZV</div>
                  <span>ZValves · Amazon</span>
                </div>
                <div className="brand-row__metric">$298K / mo</div>
                <div className="brand-row__change change-up">▲ 51.4%</div>
              </div>
              <div className="brand-row">
                <div className="brand-row__name">
                  <div className="brand-avatar a4">ND</div>
                  <span>Nut Dreamers · Both</span>
                </div>
                <div className="brand-row__metric">$94K / mo</div>
                <div className="brand-row__change change-up">▲ 17.9%</div>
              </div>
              <div className="brand-row">
                <div className="brand-row__name">
                  <div className="brand-avatar a5">RM</div>
                  <span>Remnant · AI Ops</span>
                </div>
                <div className="brand-row__metric">42 hrs / wk</div>
                <div className="brand-row__change change-down">▼ 68% load</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* TRUST BADGES */}
      <section className="trust-band">
        <div className="container">
          <div className="trust-grid">
            <div className="trust-badge reveal">
              <div className="trust-badge__accent">No.1</div>
              <div className="trust-badge__label">Family-run PPC partner<br/>in Southeast Asia</div>
            </div>
            <div className="trust-badge reveal">
              <div className="trust-badge__accent">60+</div>
              <div className="trust-badge__label">Brands scaled<br/>across 4 continents</div>
            </div>
            <div className="trust-badge reveal">
              <div className="trust-badge__accent">4.2x</div>
              <div className="trust-badge__label">Average ROAS lift<br/>in first 90 days</div>
            </div>
            <div className="trust-badge reveal">
              <div className="trust-badge__accent">98%</div>
              <div className="trust-badge__label">Client retention<br/>after year one</div>
            </div>
          </div>
        </div>
      </section>

      {/* SERVICES */}
      <section className="section" id="services">
        <div className="container">
          <div className="section-head reveal">
            <div className="eyebrow">What we do</div>
            <h2 className="section-title">Three services. One family.</h2>
            <p className="section-sub">
              Most agencies do one thing. We do the three that matter most to a modern e-commerce brand — and we run them as a single, family-owned system, not three disconnected retainers.
            </p>
          </div>

          <div className="service-grid">

            {/* Service 01: Amazon */}
            <div className="service-card reveal">
              <div className="service-card__illus">
                <svg viewBox="0 0 240 140" xmlns="http://www.w3.org/2000/svg">
                  <ellipse cx="120" cy="128" rx="90" ry="4" fill="#0B0E11" opacity="0.4"/>
                  <path d="M60 70 L120 45 L180 70 L180 115 L120 140 L60 115 Z" fill="#FCD535"/>
                  <path d="M60 70 L120 95 L180 70" stroke="#181A20" strokeWidth="2" fill="none"/>
                  <path d="M120 95 L120 140" stroke="#181A20" strokeWidth="2"/>
                  <path d="M60 70 L120 45 L180 70" stroke="#F0B90B" strokeWidth="3" fill="none"/>
                  <path d="M95 57 L145 57" stroke="#181A20" strokeWidth="2" opacity="0.4"/>
                  <path d="M195 60 L215 40 L215 55 L225 55" stroke="#FCD535" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                  <circle cx="215" cy="40" r="4" fill="#FCD535"/>
                  <rect x="20" y="90" width="8" height="20" fill="#2B3139"/>
                  <rect x="32" y="80" width="8" height="30" fill="#2B3139"/>
                  <rect x="44" y="65" width="8" height="45" fill="#FCD535"/>
                </svg>
              </div>
              <div className="service-card__num">01 / AMAZON</div>
              <h3 className="service-card__title">Amazon Account Management</h3>
              <p className="service-card__desc">
                Full-stack Amazon growth. We run your Seller Central like operators, not consultants.
              </p>
              <ul className="service-card__list">
                <li>Sponsored Products, Brands, Display, DSP</li>
                <li>Listing optimization + A+ Content</li>
                <li>Search rank + SEO indexing</li>
                <li>Bulk file audits, negatives, harvesting</li>
                <li>Weekly reporting + monthly strategy call</li>
              </ul>
              <a href="#book" className="service-card__link">Book PPC audit →</a>
            </div>

            {/* Service 02: Shopify */}
            <div className="service-card reveal">
              <div className="service-card__illus">
                <svg viewBox="0 0 240 140" xmlns="http://www.w3.org/2000/svg">
                  <ellipse cx="120" cy="128" rx="80" ry="4" fill="#0B0E11" opacity="0.4"/>
                  <rect x="55" y="45" width="130" height="75" rx="4" fill="#1E2329" stroke="#FCD535" strokeWidth="2"/>
                  <rect x="65" y="55" width="110" height="55" rx="2" fill="#2B3139"/>
                  <path d="M40 120 L200 120 L210 130 L30 130 Z" fill="#FCD535"/>
                  <path d="M85 68 L155 68 L152 78 L88 78 Z" fill="#FCD535"/>
                  <rect x="90" y="78" width="60" height="24" fill="#1E2329"/>
                  <rect x="115" y="82" width="10" height="20" fill="#FCD535"/>
                  <path d="M92 68 L92 78 M100 68 L100 78 M108 68 L108 78 M116 68 L116 78 M124 68 L124 78 M132 68 L132 78 M140 68 L140 78 M148 68 L148 78" stroke="#181A20" strokeWidth="1" opacity="0.6"/>
                  <circle cx="195" cy="40" r="14" fill="#FCD535"/>
                  <path d="M188 37 L192 37 L194 45 L200 45 L202 39 L193 39" stroke="#181A20" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                  <circle cx="196" cy="48" r="1.5" fill="#181A20"/>
                  <circle cx="199" cy="48" r="1.5" fill="#181A20"/>
                </svg>
              </div>
              <div className="service-card__num">02 / SHOPIFY</div>
              <h3 className="service-card__title">Shopify Dev &amp; Management</h3>
              <p className="service-card__desc">
                Theme development, CRO, and technical maintenance for Shopify brands that treat the store as a product.
              </p>
              <ul className="service-card__list">
                <li>Custom Liquid sections + theme development</li>
                <li>Speed, Core Web Vitals, and CVR fixes</li>
                <li>Klaviyo + Judge.me + subscription apps</li>
                <li>Metafields, Flow, and headless integrations</li>
                <li>Ongoing feature roadmap + hotfixes</li>
              </ul>
              <a href="#book" className="service-card__link">Book store audit →</a>
            </div>

            {/* Service 03: AI Automation */}
            <div className="service-card reveal">
              <div className="service-card__illus">
                <svg viewBox="0 0 240 140" xmlns="http://www.w3.org/2000/svg">
                  <ellipse cx="120" cy="128" rx="80" ry="4" fill="#0B0E11" opacity="0.4"/>
                  <path d="M55 70 L100 50 L145 90 L195 60" stroke="#FCD535" strokeWidth="2" fill="none" strokeDasharray="4 4"/>
                  <path d="M55 70 L100 50" stroke="#FCD535" strokeWidth="2" fill="none"/>
                  <path d="M100 50 L145 90" stroke="#FCD535" strokeWidth="2" fill="none"/>
                  <path d="M145 90 L195 60" stroke="#FCD535" strokeWidth="2" fill="none"/>
                  <rect x="40" y="55" width="30" height="30" rx="6" fill="#FCD535"/>
                  <path d="M48 70 L52 74 L62 64" stroke="#181A20" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                  <rect x="85" y="35" width="30" height="30" rx="6" fill="#1E2329" stroke="#FCD535" strokeWidth="2"/>
                  <circle cx="100" cy="50" r="4" fill="#FCD535"/>
                  <circle cx="100" cy="50" r="8" fill="none" stroke="#FCD535" strokeWidth="1.5"/>
                  <rect x="130" y="75" width="30" height="30" rx="6" fill="#2B3139" stroke="#FCD535" strokeWidth="2"/>
                  <path d="M138 90 L145 90 M138 85 L152 85 M138 95 L149 95" stroke="#FCD535" strokeWidth="2" strokeLinecap="round"/>
                  <rect x="180" y="45" width="30" height="30" rx="6" fill="#FCD535"/>
                  <path d="M195 52 L195 68 M187 60 L203 60" stroke="#181A20" strokeWidth="2.5" strokeLinecap="round"/>
                  <circle cx="215" cy="95" r="8" fill="none" stroke="#FCD535" strokeWidth="2"/>
                  <circle cx="215" cy="95" r="3" fill="#FCD535"/>
                </svg>
              </div>
              <div className="service-card__num">03 / AI OPS</div>
              <h3 className="service-card__title">AI Automation</h3>
              <p className="service-card__desc">
                We wire your stack together with n8n, Zapier, and Make — plus LLM steps where they earn their keep. Workflows that run 24/7, not one-off prompts.
              </p>
              <ul className="service-card__list">
                <li>n8n, Zapier, and Make workflow builds</li>
                <li>API + webhook integrations across your tools</li>
                <li>GPT / Claude steps inside automations</li>
                <li>Auto-reports, alerts, and data sync jobs</li>
                <li>CS, ops, and inventory automation</li>
              </ul>
              <a href="#book" className="service-card__link">Book ops audit →</a>
            </div>

          </div>
        </div>
      </section>

      {/* STATS BAND */}
      <section className="stats-band">
        <div className="container">
          <h2 className="stats-headline reveal">FAMILIA HAS THE RECEIPTS.</h2>
          <div className="stats-grid">
            <div className="stat reveal">
              <div className="stat__num">$48.2M</div>
              <div className="stat__label">Client revenue driven</div>
            </div>
            <div className="stat reveal">
              <div className="stat__num">4.2x</div>
              <div className="stat__label">Avg ROAS in 90 days</div>
            </div>
            <div className="stat reveal">
              <div className="stat__num">60+</div>
              <div className="stat__label">Brands managed</div>
            </div>
            <div className="stat reveal">
              <div className="stat__num">18,400</div>
              <div className="stat__label">Ops hours automated</div>
            </div>
          </div>
        </div>
      </section>

      {/* PROCESS */}
      <section className="section" id="process">
        <div className="container">
          <div className="section-head reveal">
            <div className="eyebrow">How we work</div>
            <h2 className="section-title">Audit. Strategy. Execute. Scale.</h2>
            <p className="section-sub">
              No slide-deck theater. Every engagement follows the same four-stage system — because it works, and because you deserve to know exactly what you're paying for.
            </p>
          </div>

          <div className="process-grid">
            <div className="process-step reveal">
              <div className="process-step__num">01</div>
              <h4 className="process-step__title">Audit</h4>
              <p className="process-step__desc">
                Deep-dive review of your account, store, or ops. You get a written report — yours to keep, whether you hire us or not.
              </p>
            </div>
            <div className="process-step reveal">
              <div className="process-step__num">02</div>
              <h4 className="process-step__title">Strategy</h4>
              <p className="process-step__desc">
                90-day roadmap with numbered priorities, tied to a revenue or efficiency target. Approved by you before anything ships.
              </p>
            </div>
            <div className="process-step reveal">
              <div className="process-step__num">03</div>
              <h4 className="process-step__title">Execute</h4>
              <p className="process-step__desc">
                Weekly execution against the roadmap. Slack access, live dashboards, and a named family lead who owns the outcome.
              </p>
            </div>
            <div className="process-step reveal">
              <div className="process-step__num">04</div>
              <h4 className="process-step__title">Scale</h4>
              <p className="process-step__desc">
                Once the system is working, we expand into new markets, categories, or automation layers. No lock-in — you can leave any month.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* TEAM */}
      <section className="section" id="team">
        <div className="container">
          <div className="section-head center reveal">
            <div className="family-badge">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              <span>The Family</span>
            </div>
            <h2 className="section-title">Meet the Familia.</h2>
            <p className="section-sub">
              We're not a rotating cast of freelancers. FamiliaOps is a family-owned business — every account is run by someone whose last name is on the door.
            </p>
          </div>

          <div className="team-grid">

            <div className="team-card reveal">
              <div className="team-avatar">
                <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="50" cy="35" r="18" fill="#F3B7A0"/>
                  <path d="M32 30 Q50 12 68 30 L68 25 Q50 8 32 25 Z" fill="#1E2329"/>
                  <circle cx="43" cy="35" r="1.5" fill="#181A20"/>
                  <circle cx="57" cy="35" r="1.5" fill="#181A20"/>
                  <path d="M45 42 Q50 46 55 42" stroke="#181A20" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                  <path d="M22 100 Q22 68 50 62 Q78 68 78 100 Z" fill="#FCD535"/>
                  <path d="M42 62 L50 72 L58 62" fill="#1E2329"/>
                </svg>
              </div>
              <div className="team-name">[Founder Name]</div>
              <div className="team-role">Founder · Head of Ops</div>
              <p className="team-bio">
                Started FamiliaOps in 2020 after 5 years running Amazon accounts in-house for brands. Sets the standard for how the family works.
              </p>
              <div className="team-socials">
                <a href="#" aria-label="LinkedIn"><LinkedInIcon /></a>
                <a href="#" aria-label="Email"><EmailIcon /></a>
              </div>
            </div>

            <div className="team-card reveal">
              <div className="team-avatar">
                <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                  <path d="M28 40 Q28 65 32 78 L26 78 Q24 55 28 35 Z" fill="#1E2329"/>
                  <path d="M72 40 Q72 65 68 78 L74 78 Q76 55 72 35 Z" fill="#1E2329"/>
                  <circle cx="50" cy="38" r="18" fill="#F3B7A0"/>
                  <path d="M32 32 Q50 14 68 32 L68 42 Q65 30 50 26 Q35 30 32 42 Z" fill="#1E2329"/>
                  <circle cx="43" cy="38" r="1.5" fill="#181A20"/>
                  <circle cx="57" cy="38" r="1.5" fill="#181A20"/>
                  <path d="M46 46 Q50 49 54 46" stroke="#181A20" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                  <path d="M22 100 Q22 70 50 64 Q78 70 78 100 Z" fill="#FCD535"/>
                  <path d="M42 64 L50 74 L58 64" fill="#1E2329"/>
                </svg>
              </div>
              <div className="team-name">[Team Member Name]</div>
              <div className="team-role">Amazon Lead</div>
              <p className="team-bio">
                Owns every Amazon account under FamiliaOps. Amazon Ads certified. Runs bulk-file audits like most people run laundry.
              </p>
              <div className="team-socials">
                <a href="#" aria-label="LinkedIn"><LinkedInIcon /></a>
                <a href="#" aria-label="Email"><EmailIcon /></a>
              </div>
            </div>

            <div className="team-card reveal">
              <div className="team-avatar">
                <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="50" cy="36" r="18" fill="#F3B7A0"/>
                  <path d="M32 30 Q38 15 55 18 Q68 22 68 32 L60 32 Q55 24 45 26 Q35 28 32 34 Z" fill="#1E2329"/>
                  <circle cx="43" cy="37" r="4" fill="none" stroke="#181A20" strokeWidth="1.5"/>
                  <circle cx="57" cy="37" r="4" fill="none" stroke="#181A20" strokeWidth="1.5"/>
                  <path d="M47 37 L53 37" stroke="#181A20" strokeWidth="1.5"/>
                  <path d="M40 46 Q50 52 60 46" stroke="#1E2329" strokeWidth="2" fill="none" opacity="0.6"/>
                  <path d="M22 100 Q22 68 50 62 Q78 68 78 100 Z" fill="#FCD535"/>
                  <path d="M42 62 L50 72 L58 62" fill="#1E2329"/>
                </svg>
              </div>
              <div className="team-name">[Team Member Name]</div>
              <div className="team-role">Shopify Lead</div>
              <p className="team-bio">
                Writes Liquid, ships themes, and hunts down every millisecond of Core Web Vitals. 40+ stores shipped since 2021.
              </p>
              <div className="team-socials">
                <a href="#" aria-label="LinkedIn"><LinkedInIcon /></a>
                <a href="#" aria-label="Email"><EmailIcon /></a>
              </div>
            </div>

            <div className="team-card reveal">
              <div className="team-avatar">
                <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="50" cy="36" r="18" fill="#F3B7A0"/>
                  <path d="M30 34 Q30 18 50 15 Q70 18 70 34 L70 44 Q65 32 50 30 Q35 32 30 44 Z" fill="#1E2329"/>
                  <path d="M30 42 Q28 50 32 55 L34 46 Z" fill="#1E2329"/>
                  <path d="M70 42 Q72 50 68 55 L66 46 Z" fill="#1E2329"/>
                  <circle cx="43" cy="37" r="1.5" fill="#181A20"/>
                  <circle cx="57" cy="37" r="1.5" fill="#181A20"/>
                  <path d="M45 44 Q50 48 55 44" stroke="#181A20" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                  <circle cx="32" cy="40" r="1.5" fill="#FCD535"/>
                  <circle cx="68" cy="40" r="1.5" fill="#FCD535"/>
                  <path d="M22 100 Q22 70 50 64 Q78 70 78 100 Z" fill="#FCD535"/>
                  <path d="M42 64 L50 74 L58 64" fill="#1E2329"/>
                </svg>
              </div>
              <div className="team-name">[Team Member Name]</div>
              <div className="team-role">AI Automation Lead</div>
              <p className="team-bio">
                Builds n8n, Zapier, and Make workflows that quietly remove hours from client ops teams. Loves a well-wired webhook.
              </p>
              <div className="team-socials">
                <a href="#" aria-label="LinkedIn"><LinkedInIcon /></a>
                <a href="#" aria-label="Email"><EmailIcon /></a>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* RESULTS TABLE */}
      <section className="section" id="results">
        <div className="container">
          <div className="section-head reveal">
            <div className="eyebrow">Live results</div>
            <h2 className="section-title">Recent client wins.</h2>
            <p className="section-sub">
              Real accounts. Real numbers. Every result below verifiable in a client reference call.
            </p>
          </div>

          <div className="results-card reveal">
            <div className="results-tabs">
              {['All wins', 'Amazon', 'Shopify', 'AI Ops'].map((t, i) => (
                <button key={t} className={`results-tab${resultsTab === i ? ' active' : ''}`}
                  onClick={() => setResultsTab(i)}>{t}</button>
              ))}
            </div>

            <div style={{ overflowX: 'auto' }}>
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Brand</th>
                    <th>Service</th>
                    <th>Result</th>
                    <th>Timeframe</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a1">PI</div><span>Pro Ice</span></div></td>
                    <td><span className="svc-pill">Amazon PPC</span></td>
                    <td><span className="change-up"><span className="change-arrow">▲</span>ACoS 41% → 18%</span></td>
                    <td>90 days</td>
                  </tr>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a2">LF</div><span>Louis Foster Racing</span></div></td>
                    <td><span className="svc-pill">Shopify Theme</span></td>
                    <td><span className="change-up"><span className="change-arrow">▲</span>CVR +2.4pp</span></td>
                    <td>45 days</td>
                  </tr>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a3">ZV</div><span>ZValves</span></div></td>
                    <td><span className="svc-pill">Amazon Full</span></td>
                    <td><span className="change-up"><span className="change-arrow">▲</span>Revenue +51%</span></td>
                    <td>6 months</td>
                  </tr>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a5">RM</div><span>Remnant Co.</span></div></td>
                    <td><span className="svc-pill">AI Automation</span></td>
                    <td><span className="change-down"><span className="change-arrow">▼</span>Ops load -68%</span></td>
                    <td>60 days</td>
                  </tr>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a4">ND</div><span>Nut Dreamers</span></div></td>
                    <td><span className="svc-pill">Amazon SEO</span></td>
                    <td><span className="change-up"><span className="change-arrow">▲</span>Organic rank #14 → #2</span></td>
                    <td>4 months</td>
                  </tr>
                  <tr>
                    <td><div className="brand-cell"><div className="brand-avatar a1">HB</div><span>Harbor Goods</span></div></td>
                    <td><span className="svc-pill">Shopify CRO</span></td>
                    <td><span className="change-up"><span className="change-arrow">▲</span>AOV $47 → $71</span></td>
                    <td>75 days</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* BOOK CALL PROMO */}
      <section className="section" id="book">
        <div className="container">
          <div className="promo-grid">
            <div className="promo-card reveal">
              <div>
                <div className="eyebrow">Free audit</div>
                <h3>Book a 30-minute audit call with a member of the family.</h3>
                <p>
                  Send us your Amazon account, Shopify store, or an ops workflow. We'll walk through what we'd fix in the first 30 days, live on the call — yours to take with you either way.
                </p>
              </div>
              <div className="promo-actions">
                <a href="#" className="btn-primary">Book audit</a>
                <a href="mailto:hello@familiaops.co" className="btn-text">or email us →</a>
              </div>
            </div>

            <div className="promo-illus-card reveal">
              <svg viewBox="0 0 240 200" xmlns="http://www.w3.org/2000/svg">
                <ellipse cx="120" cy="188" rx="90" ry="5" fill="#0B0E11" opacity="0.4"/>
                <path d="M50 180 L190 180 L200 190 L40 190 Z" fill="#FCD535"/>
                <rect x="55" y="90" width="130" height="90" rx="4" fill="#1E2329" stroke="#FCD535" strokeWidth="2"/>
                <rect x="62" y="97" width="116" height="76" rx="2" fill="#2B3139"/>
                <circle cx="120" cy="125" r="14" fill="#F3B7A0"/>
                <path d="M108 122 Q120 108 132 122 L132 118 Q120 106 108 118 Z" fill="#1E2329"/>
                <circle cx="115" cy="126" r="1.2" fill="#181A20"/>
                <circle cx="125" cy="126" r="1.2" fill="#181A20"/>
                <path d="M117 131 Q120 133 123 131" stroke="#181A20" strokeWidth="1" fill="none" strokeLinecap="round"/>
                <path d="M100 168 Q100 148 120 144 Q140 148 140 168 Z" fill="#FCD535"/>
                <circle cx="72" cy="167" r="3" fill="#F6465D"/>
                <circle cx="82" cy="167" r="3" fill="#0ECB81"/>
                <rect x="150" y="163" width="20" height="8" rx="2" fill="#FCD535"/>
                <path d="M195 50 Q220 50 220 65 Q220 78 205 78 L200 85 L200 78 Q195 78 195 65 Z" fill="#FCD535"/>
                <circle cx="205" cy="65" r="1.5" fill="#181A20"/>
                <circle cx="210" cy="65" r="1.5" fill="#181A20"/>
                <circle cx="215" cy="65" r="1.5" fill="#181A20"/>
                <path d="M20 165 L35 165 L33 180 L22 180 Z" fill="#FCD535"/>
                <path d="M35 168 Q42 168 42 173 Q42 178 35 178" stroke="#FCD535" strokeWidth="2" fill="none"/>
                <path d="M25 158 Q27 155 25 152 M30 158 Q32 155 30 152" stroke="#929AA5" strokeWidth="1.5" fill="none" opacity="0.6"/>
              </svg>
              <div className="promo-illus-label">30 min · Google Meet · No pitch</div>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="section" id="faq">
        <div className="container">
          <div className="section-head center reveal">
            <div className="eyebrow">FAQ</div>
            <h2 className="section-title">Common questions.</h2>
          </div>

          <div className="faq-list">
            {FAQS.map(([q, a], i) => (
              <div key={q} className={`faq-row${openFaq.has(i) ? ' open' : ''}`}>
                <button className="faq-btn" onClick={() => toggleFaq(i)}>
                  <span>{q}</span>
                  <ChevronIcon />
                </button>
                <div className="faq-answer"><p>{a}</p></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA BAND */}
      <section>
        <div className="container">
          <div className="cta-band reveal">
            <h3>Ready to scale? The family is ready when you are.</h3>
            <a href="#book" className="btn-primary-pill">Get free audit</a>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="footer">
        <div className="container">
          <div className="footer-grid">
            <div className="footer-brand-col">
              <a href="#" className="brand">
                <span className="brand-mark">F</span>
                <span>FamiliaOps</span>
              </a>
              <p>A family-run digital services agency. Amazon, Shopify, and AI Automation — one team, one accountable roadmap.</p>
            </div>
            <div className="footer-col">
              <h4>Services</h4>
              <ul>
                <li><a href="#services">Amazon Management</a></li>
                <li><a href="#services">Shopify Development</a></li>
                <li><a href="#services">AI Automation</a></li>
                <li><a href="#services">Free Audit</a></li>
              </ul>
            </div>
            <div className="footer-col">
              <h4>Company</h4>
              <ul>
                <li><a href="#team">The Family</a></li>
                <li><a href="#results">Case Studies</a></li>
                <li><a href="#process">Process</a></li>
                <li><a href="#">Careers</a></li>
              </ul>
            </div>
            <div className="footer-col">
              <h4>Resources</h4>
              <ul>
                <li><a href="#">Blog</a></li>
                <li><a href="#">PPC Playbook</a></li>
                <li><a href="#">Shopify Guides</a></li>
                <li><a href="#faq">FAQ</a></li>
              </ul>
            </div>
            <div className="footer-col">
              <h4>Contact</h4>
              <ul>
                <li><a href="mailto:hello@familiaops.co">hello@familiaops.co</a></li>
                <li><a href="#book">Book a call</a></li>
                <li><a href="/login">Client login</a></li>
              </ul>
            </div>
          </div>
          <div className="footer-bottom">
            <div>© 2026 FamiliaOps. All rights reserved.</div>
            <div className="socials">
              <a href="#" aria-label="Twitter"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
              <a href="#" aria-label="LinkedIn"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.063 2.063 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/></svg></a>
              <a href="#" aria-label="Email"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg></a>
            </div>
          </div>
        </div>
      </footer>

    </div>
  )
}
