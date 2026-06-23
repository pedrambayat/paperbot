# Lab Paper Summarizer Slack Bot — Product Document

**Status** Draft v0.1
**Owner** Pedram
**Last updated** June 23, 2026

---

## 1. Summary

A Slack app that watches the lab's papers channel, detects when someone shares a paper, retrieves it, generates a structured summary with an LLM, and posts that summary back as a threaded reply on the original message. The goal is to lower the cost of staying current with the literature the lab cares about and to leave behind a searchable record of what was shared and why it mattered.

This document covers the problem, scope, requirements, architecture, the paper retrieval strategy (the hard part), the summarization design, deployment, cost, and a phased rollout. Open decisions are flagged inline as **Open question** callouts.

---

## 2. Problem and motivation

Lab members drop papers into a Slack channel faster than anyone can read them. Most links get a reaction emoji and then disappear up the scroll. The friction of opening a PDF, skimming the abstract, finding the actual result, and deciding whether it is worth a deeper read is small per paper but large in aggregate, so papers go unread and context gets lost.

A bot that posts a tight, consistent summary under each shared paper does three things. It lets people triage at a glance whether a paper is relevant to their work. It creates a uniform format so summaries are comparable across papers. And it builds a durable, searchable archive of the lab's reading, which is useful for onboarding new members and for writing related-work sections later.

---

## 3. Goals and non-goals

### Goals

The bot should summarize any open-access paper shared in the channel with no manual steps. Summaries should be accurate, skimmable, and consistently formatted. The system should run reliably without daily babysitting, cost very little, and be simple enough for one person to maintain.

### Non-goals for v1

Full institutional access to paywalled journals is out of scope for the first version. So is interactive question answering against a paper, figure and table understanding beyond what the LLM extracts from text, support for channels other than the single papers channel, and any kind of citation-graph or recommendation feature. These are candidates for later versions, not v1.

> **Open question 1.** Is summarizing only open-access papers (arXiv, bioRxiv, medRxiv, and any paper with a free full-text version) acceptable for v1, with paywalled-only papers getting an abstract-only summary or being skipped? Or is full-text coverage of paywalled journals a hard requirement from day one?

---

## 4. Users

The primary users are everyone in the lab Slack, spanning the PI, postdocs, grad students, and undergrads. They fall into two roles.

A **sharer** posts a paper link to the channel. They want the summary to appear quickly and quietly without cluttering the channel.

A **reader** scrolls the channel and reads summaries to decide what to engage with. They want a format that surfaces the method and the main result fast.

There is no admin persona beyond you as the maintainer.

---

## 5. User stories

As a sharer, when I paste an arXiv link, a summary appears in the thread within a minute so I do not have to write my own blurb.

As a reader, I can read a four-line summary and know the method and headline result without opening the PDF.

As a reader, I can search the channel for a keyword and find papers we discussed months ago along with their summaries.

As the maintainer, when retrieval fails for a paper, the bot tells me why in a way I can debug rather than failing silently.

---

## 6. Functional requirements

Priorities use P0 for v1-critical, P1 for soon-after, P2 for later.

The bot detects paper links posted in the configured channel (P0). It resolves a link to a canonical paper identity, meaning an arXiv ID, a DOI, or a bioRxiv/medRxiv DOI (P0). It retrieves the full text when an open version exists, and falls back to the abstract otherwise (P0). It generates a structured summary with an LLM (P0). It posts the summary as a threaded reply to the original message (P0). It handles multiple links in one message (P1). It avoids re-summarizing a paper already summarized in the channel (P1). It persists summaries and metadata to a small store for later search and digests (P1). It reacts to the source message with a status emoji such as an hourglass while working and a check when done (P2). It supports an emoji-triggered mode where it only summarizes on a specific reaction rather than automatically (P2).

> **Open question 2.** Should the bot trigger automatically on every detected link, or only when someone adds a specific trigger emoji to a message? Auto is zero-friction but can feel noisy. Emoji-trigger is opt-in per paper and avoids summarizing things people just wanted to bookmark.

---

## 7. System architecture

### 7.1 High level flow

```
Slack papers channel
        |
   (event: message or reaction)
        v
  Bolt app (Socket Mode)  ---- always-on process
        |
        v
  Link detector  ->  Paper resolver (ID / DOI)
        |
        v
  Retriever  ->  full-text PDF  or  abstract fallback
        |
        v
  Summarizer (LLM with document input)
        |
        v
  Formatter  ->  Slack Block Kit message
        |
        v
  Post threaded reply  +  (optional) persist to store
```

### 7.2 Components

The **Slack listener** is a Bolt for Python app running in Socket Mode. Socket Mode opens an outbound websocket to Slack, so there is no public HTTP endpoint to expose and no inbound networking to manage. This is the right choice for something running on a single small instance or a lab machine.

The **link detector** scans message text for URLs and known patterns such as `arxiv.org/abs`, `biorxiv.org`, `medrxiv.org`, `doi.org`, and common publisher domains. It extracts candidate paper references.

The **paper resolver** turns a messy URL into a canonical identifier. An arXiv URL becomes an arXiv ID. A publisher or doi.org URL becomes a DOI. This canonical ID is what everything downstream keys on, including dedupe.

The **retriever** is the crux of the system and gets its own section below.

The **summarizer** sends the retrieved content to an LLM and gets back a structured summary. Where the provider supports native document input, the PDF goes in directly so we skip our own text extraction.

The **formatter** turns the summary into Slack Block Kit so it renders cleanly with bold field labels and spacing rather than a wall of text.

The optional **store** is a lightweight database (SQLite to start) holding the canonical ID, title, authors, source URL, summary, who shared it, and a timestamp. This powers dedupe now and search or weekly digests later.

> **Open question 3.** Do you want persistence in v1 (enables dedupe, search, and a future weekly digest), or is a stateless bot that just posts and forgets fine for the first cut?

---

## 8. Paper retrieval strategy

This is where feasibility actually lives. The plan is a cascade that tries the cheapest reliable source first and degrades gracefully.

### 8.1 arXiv

arXiv links resolve to an arXiv ID. The arXiv API returns metadata, and the PDF is directly fetchable at a predictable URL. This path is clean and covers a large share of ML-for-bio preprints. Reliability here is high.

### 8.2 bioRxiv and medRxiv

Both expose a public API keyed on DOI that returns metadata and a link to the full-text PDF. Coverage of the lab's preprint reading should be strong. Reliability is good, with the occasional very recent posting not yet indexed.

### 8.3 Published papers with a DOI

For anything with a DOI, the flow is to pull metadata from Crossref, then ask **Unpaywall** whether a legal open-access full-text version exists. Unpaywall is a free DOI-to-open-access service that frequently finds an author manuscript or a repository copy of a paper that is paywalled at the publisher. In biology and ML this hits surprisingly often because of preprint and PMC deposits. When Unpaywall returns an open PDF, we summarize the full text. **OpenAlex** and **Semantic Scholar** are good secondary sources for metadata and abstracts and can also surface open PDF links.

### 8.4 Paywalled with no open version

When no open full text exists, the bot summarizes the abstract only and labels the summary clearly as abstract-based so no one mistakes a thin summary for a full read. This is the graceful-degradation floor.

### 8.5 Retrieval cascade

```
resolve ID
  -> arXiv?      -> arXiv PDF
  -> bioRxiv?    -> bioRxiv PDF
  -> medRxiv?    -> medRxiv PDF
  -> has DOI?    -> Unpaywall open PDF?
                     -> yes: full text
                     -> no:  Crossref / OpenAlex abstract  (labeled abstract-only)
  -> none of the above -> post a polite "could not retrieve" note
```

> **Open question 4.** When the bot can only get the abstract, do you want it to (a) post a clearly-labeled abstract-only summary, or (b) stay silent and only summarize papers it can read in full? Option (a) maximizes coverage, option (b) keeps quality uniform.

---

## 9. Summarization design

### 9.1 Input

Where the LLM provider accepts native PDF input, pass the PDF straight through. This avoids the worst part of homegrown pipelines, which is parsing multi-column layouts, figure captions, and reference lists. For abstract-only cases, pass the abstract text plus title and authors.

### 9.2 Output format

A good default for a lab channel is a compact, fixed structure so summaries are comparable. A reasonable template is a one-line TL;DR, the problem being addressed, the method or key idea, the headline result with any concrete numbers, and one line on limitations or what to watch for. Keeping it to roughly five short fields makes summaries skimmable in the channel.

> **Open question 5.** What summary depth do you want? A tight five-line TL;DR-style card, a medium structured summary with a few sentences per section, or a longer detailed breakdown? This drives both readability and per-paper cost.

> **Open question 6.** Do you want the bot tuned for the lab's specific interests, for example always calling out the experimental system, whether there are wet-lab validations, dataset size, and whether negatives were experimentally verified? A field-tuned prompt produces much more useful summaries than a generic one.

### 9.3 Model

Any major provider with document input works. The choice comes down to which API keys you already have, the quality bar for technical bio papers, and per-paper cost. Pricing changes often, so the specific model and its cost should be confirmed against current provider pricing at build time rather than assumed.

> **Open question 7.** Which LLM provider do you want to build against? The natural answer is whatever you already have credits or keys for, so I can write the integration against that directly.

---

## 10. Slack integration details

The app needs a Slack app created in the workspace with a bot token and an app-level token for Socket Mode. The bot scopes required are reading channel history in the papers channel, writing messages, and, if using the emoji-trigger or status-emoji features, reading and writing reactions. The event subscriptions are message events in the channel for auto mode, or reaction-added events for emoji-trigger mode.

Block Kit is used for the summary message so field labels render in bold and the card is readable. The summary is always posted as a threaded reply on the source message so the main channel stays clean.

A practical note on permissions. Installing an app and granting it channel history access is something the workspace admin has to approve. If you are not a Slack admin for the lab workspace, this needs a quick sign-off from whoever is.

> **Open question 8.** Are you an admin on the lab Slack, or will installing the app need approval from someone else? This affects how fast you can ship.

---

## 11. Deployment and operations

The bot is a single always-on Python process. Given your AWS familiarity, a small instance such as a t4g.small running the app under systemd is a clean home, and it is cheap. A lab machine or even a Raspberry Pi works equally well because Socket Mode needs only outbound networking.

Secrets, meaning the Slack tokens and the LLM API key, live in environment variables or in AWS SSM Parameter Store rather than in code. Logs go to a file or to CloudWatch so retrieval failures are debuggable. A simple restart policy under systemd covers crashes.

> **Open question 9.** Where do you want this to run, on an EC2 instance, on a lab machine you control, or somewhere else? And do you want it to live in a lab repo or a personal one?

---

## 12. Cost

There are two cost lines and both are small.

The LLM cost is per paper. A full paper is on the order of ten to twenty thousand input tokens, so the per-paper summarization cost is roughly a few cents to low tens of cents depending on the model. At a realistic lab volume of a handful of papers a day, this is a few dollars a month at most. Confirm against current pricing for the chosen model.

The hosting cost is a small instance running continuously, which is single-digit dollars a month, or zero if it runs on existing lab hardware.

The total expected run cost is comfortably under the price of a couple of coffees per month at typical lab volume.

---

## 13. Phased rollout

**v1, the core loop.** Auto-detect arXiv, bioRxiv, and medRxiv links. Retrieve full text. Summarize with the chosen model and a field-tuned prompt. Post a threaded reply. No persistence, no paywall handling beyond skipping. This is the evening-or-two build.

**v2, coverage and control.** Add DOI resolution with Unpaywall and OpenAlex so published papers and paywalled-but-open papers are covered. Add the abstract-only fallback with clear labeling. Add persistence for dedupe. Optionally add the emoji-trigger mode and status emojis.

**v3, leverage on the archive.** A weekly digest that posts a roundup of the week's papers. Channel search or a slash command to ask questions across stored summaries. Possible per-person relevance tagging.

---

## 14. Success metrics

The bot is working if a large majority of shared open-access papers get a summary automatically, summaries land within about a minute, and the failure rate on supported sources stays low. The softer signal is whether lab members start relying on the summaries to triage, which shows up as reactions and thread replies on the bot's posts rather than on the raw links.

---

## 15. Risks and mitigations

The main risk is paper access for paywalled journals, mitigated by the Unpaywall cascade and the abstract-only floor. A second risk is summary quality on dense technical papers, mitigated by a field-tuned prompt and by choosing a capable model. A third is Slack admin approval for installation, mitigated by sorting out permissions early. A fourth is silent failure, mitigated by status emojis and clear error replies so problems are visible rather than hidden.

---

## 16. Consolidated open questions

1. Is open-access-only acceptable for v1, with paywalled papers degraded to abstract-only or skipped?
2. Auto-summarize on every link, or emoji-triggered opt-in?
3. Persistence in v1, or stateless to start?
4. On abstract-only papers, post a labeled summary or stay silent?
5. Summary depth, short card vs medium vs detailed?
6. Tune the prompt for the lab's specific interests, and which fields matter most?
7. Which LLM provider to build against?
8. Are you a Slack admin, or is install approval needed?
9. Where should it run, and which repo should it live in?
