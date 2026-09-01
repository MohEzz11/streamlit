# Path Mentor — Phase 1 Rebuild

A clean, portable, self-contained rebuild of the **path-mentor.com** homepage,
faithful to the live brand and ready to upload to Hostinger hosting (or any host).

## Files
- `index.html` — the whole page (HTML + CSS + minimal JS all inlined). Just upload this.

## What it contains
- Announcement bar ("Save 20% on coaching sessions!")
- Sticky header: logo, nav (Home / Services / Bookings / About / Path Planner), Instagram + LinkedIn, cart icon, mobile menu
- Hero with background video + overlay, headline, and CTAs
- **Services** — 3 cards (One-on-One, Career Help, Life Planning)
- **Guiding Your Next Steps** (About) — Personal Growth + Career Focus
- Testimonial (★★★★★ — J. Lee)
- **Get in Touch** — booking form (Name, Email, Preferred Date)
- Footer — contact, email, subscribe, socials, copyright

## Design system (from the live brand)
- Font: Montserrat
- Teal `#256D85`, slate `#1A2A32`, ink `#0d141a`, muted `#56585E`, mist `#E7F6F8`
- Pill buttons, 20–34px radii, subtle shadows
- Responsive (3→2→1 col), WCAG-AA contrast, reduced-motion support, keyboard focus states

## Notes / decisions
- **Restored two sections that were hidden on the live site** (Services + testimonial).
  A professional coaching page needs them; delete the `#services` and `#testimonial`
  sections if hiding them was intentional.
- **Forms are client-side only for now** (they show a success message, no backend).
  Real booking is wired in Phase 2 (Hostinger booking calendar); the downloadable
  product + discount code is Phase 3.
- Images/video use the same external Unsplash/Pexels URLs as the live site, plus the
  Hostinger-hosted logo. Swap for local files in `assets/` if you want it fully self-hosted.
- Hero "Book Now" links to the booking form (`#book`) instead of the placeholder
  `calendly.com/your-username/session` that was on the live site.
