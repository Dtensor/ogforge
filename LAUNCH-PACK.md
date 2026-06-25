# Snapcard — Phase C Organic Launch Pack (DRAFT — awaiting approval)

Product: **Snapcard** — Instant social cards for every link. https://ogforge.fly.dev
Free: 50 images/mo (watermark). Pro ₹750/mo: 5,000/mo, no watermark, custom colors, batch + story/square formats.
Channel stance: **organic only**, draft → user approves each post → publish. No cold outreach.

---

## 1. Ghost blog post (SEO) — owned channel, lowest risk

**Title:** A free Open Graph image API: dynamic social cards in one request
**Slug:** free-open-graph-image-api
**Meta description:** Generate dynamic OG / social-share images from a single API call. Free tier, no design tools, works with any link.

When you paste a link into Twitter, LinkedIn, Slack or iMessage, the preview card that
shows up is driven by one Open Graph image. Get it right and your link looks deliberate;
skip it and you ship a grey box. The problem is that making those images by hand — one per
post, per page, per product — does not scale, and the design tools that generate them are
either heavyweight or locked behind a subscription before you have shipped a thing.

Snapcard is a small API that does exactly one job well: you send it a title (and optionally
a template, colours and a format), and it returns a clean PNG social card in well under a
second. There is a live demo on the landing page — type a title and watch the card render —
so you can judge the output before you write a line of code.

The free tier is 50 images a month with a small watermark, which is enough to wire it into a
side project and see the link previews improve immediately. If you outgrow it, Pro is ₹750 a
month for 5,000 images, no watermark, custom brand colours, batch generation, and extra
formats (story and square, not just the standard landscape card). There is no build step and
no asset pipeline — it is one HTTP call you can drop into a blog template, a sitemap job, or
a CI step that backfills cards for existing pages.

It is built for the case where you have a lot of links and not a lot of time: a blog that
wants a distinct card per article, a directory that needs one per listing, a SaaS that wants
its share previews to look like the rest of the brand. Try the demo, grab a free key, and if
it saves you an afternoon of fiddling in a design tool, that is the whole point.

*Built by an indie maker; this post was drafted with AI assistance and edited before publishing.*

---

## 2. Reddit — r/SideProject (or r/webdev "Showoff Saturday")

**Title:** I built a free API that turns any link title into a social-share card (live demo, no signup to try)

Body:
I kept shipping side projects whose links looked like grey boxes when shared, and every tool
for fixing that wanted a subscription before I'd validated anything. So I built Snapcard — you
send a title to an endpoint, you get back a clean PNG social card in <1s.

There's a live demo on the landing page (no signup) — type a title, watch it render — so you
can see the output quality before committing. Free tier is 50/mo with a small watermark, which
covers a real side project. Paid is for when you've got thousands of links and want your own
brand colours + batch + story/square formats.

Link: https://ogforge.fly.dev

Honest disclosure: I'm the maker, it's a paid product above the free tier, and I used AI to
help draft this post. Genuinely after feedback on the demo output and whether the free tier is
useful enough — what would make you actually wire this in?

---

## 3. X / Twitter thread

1/ Every link you share has one image that decides if it looks deliberate or like a grey box: the Open Graph card. Making them by hand doesn't scale. So I built Snapcard — dynamic social cards from one API call. Live demo (no signup) 👇 https://ogforge.fly.dev

2/ You send a title (+ optional template, colours, format). You get a clean PNG card back in under a second. There's a type-to-render demo on the landing page so you can judge the output before writing any code.

3/ Free tier: 50 cards/mo, small watermark — enough to wire into a real side project today. Pro (₹750/mo): 5,000/mo, no watermark, brand colours, batch, plus story + square formats, not just landscape.

4/ Built for "lots of links, not much time": a blog wanting a card per post, a directory one per listing, a SaaS that wants share previews on-brand. One HTTP call, no asset pipeline, no build step.

5/ Try the demo, grab a free key, tell me if it saves you an afternoon. https://ogforge.fly.dev
(Maker here; paid above the free tier; thread drafted with AI help.)

---

## Posting plan (after approval)
- Ghost: `ghost-pub` (owned channel — safe to publish first, becomes the SEO anchor link).
- Reddit: via browser-harness `old.reddit.com/r/<sub>/submit` (title prefilled, body on clipboard, manual flair). Post in ONE sub first, gauge reception before others. Respect each sub's self-promo rules + Showoff day.
- X: `content-publish` → clipboard → manual paste (no API key needed).
- Disclosure line included on Reddit + X per content-publisher automation-disclosure policy.
