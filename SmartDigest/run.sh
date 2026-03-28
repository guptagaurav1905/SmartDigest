#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  SmartDigest — Pipeline Runner (Phase 4)
#
#  Usage:
#    ./run.sh --sod                 Full SOD: weather+cal+gmail+tech → all channels
#    ./run.sh --eod                 Full EOD: slack digest+tech → all channels
#    ./run.sh --sod --skip-github   Skip GitHub fetcher
#    ./run.sh --sod --preview       Compose but don't send
#    ./run.sh --channels telegram   Send to specific channel only
#    ./run.sh --dry-run             Fetch sources only, no scoring or delivery
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m';   BLUE='\033[0;34m';  NC='\033[0m'

# ── Flags ────────────────────────────────────────────────────────────────────
MODE="sod"            # sod | eod
SKIP_GITHUB=false
SKIP_SCORING=false
PREVIEW=false
DRY_RUN=false
CHANNELS=""

for arg in "$@"; do
  case $arg in
    --sod)          MODE="sod" ;;
    --eod)          MODE="eod" ;;
    --skip-github)  SKIP_GITHUB=true ;;
    --skip-scoring) SKIP_SCORING=true ;;
    --preview)      PREVIEW=true ;;
    --dry-run)      DRY_RUN=true ;;
    --channels)     shift; CHANNELS="$@"; break ;;
  esac
done

cd "$(dirname "$0")"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SmartDigest — ${MODE^^} Pipeline                  ║${NC}"
echo -e "${BLUE}║  $(date '+%a %b %d %Y — %I:%M %p')         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Load .env
if [ -f ".env" ]; then
  echo -e "${YELLOW}[env] Loading .env...${NC}"
  set -o allexport; source .env; set +o allexport
fi

# ── SOD Pipeline ─────────────────────────────────────────────────────────────
if [ "$MODE" = "sod" ]; then

  echo -e "${BLUE}▶ STAGE 1 — Fetch Personal Context (SOD)${NC}"

  # Weather (no key needed)
  echo -e "  ${YELLOW}→ Weather...${NC}"
  python scripts/fetch_weather.py && echo -e "  ${GREEN}✅ Weather${NC}" || echo -e "  ${RED}⚠️  Weather failed${NC}"

  # Google Calendar
  if [ -f "state/google_token.json" ]; then
    echo -e "  ${YELLOW}→ Calendar...${NC}"
    python scripts/fetch_calendar.py && echo -e "  ${GREEN}✅ Calendar${NC}" || echo -e "  ${RED}⚠️  Calendar failed${NC}"
  else
    echo -e "  ${YELLOW}⏭ Calendar: run setup_google.py first${NC}"
  fi

  # Gmail
  if [ -f "state/google_token.json" ]; then
    echo -e "  ${YELLOW}→ Gmail...${NC}"
    python scripts/fetch_gmail.py && echo -e "  ${GREEN}✅ Gmail${NC}" || echo -e "  ${RED}⚠️  Gmail failed${NC}"
  else
    echo -e "  ${YELLOW}⏭ Gmail: run setup_google.py first${NC}"
  fi

  echo ""
  echo -e "${BLUE}▶ STAGE 2 — Fetch Tech Sources${NC}"

  if [ "$SKIP_GITHUB" = true ] || [ -z "${GITHUB_TOKEN:-}" ]; then
    echo -e "  ${YELLOW}⏭ GitHub (no GITHUB_TOKEN)${NC}"
  else
    python scripts/fetch_github.py && echo -e "  ${GREEN}✅ GitHub${NC}" || echo -e "  ${RED}⚠️  GitHub failed${NC}"
  fi

  python scripts/fetch_hackernews.py && echo -e "  ${GREEN}✅ HackerNews${NC}" || echo -e "  ${RED}⚠️  HN failed${NC}"
  python scripts/fetch_rss.py        && echo -e "  ${GREEN}✅ RSS${NC}"        || echo -e "  ${RED}⚠️  RSS failed${NC}"
  python scripts/fetch_arxiv.py      && echo -e "  ${GREEN}✅ arXiv${NC}"      || echo -e "  ${RED}⚠️  arXiv failed${NC}"

  [ "$DRY_RUN" = true ] && { echo -e "${GREEN}[dry-run] Done.${NC}"; exit 0; }

  echo ""
  echo -e "${BLUE}▶ STAGE 3 — Score Tech Items${NC}"
  if [ "$SKIP_SCORING" = false ]; then
    if [ -n "${GROQ_API_KEY:-}" ]; then
      python scripts/groq_scorer.py && echo -e "  ${GREEN}✅ Scored with Groq${NC}" || echo -e "  ${RED}❌ Scoring failed${NC}"
    else
      echo -e "  ${YELLOW}⚠️  No GROQ_API_KEY — skipping scoring${NC}"
    fi
  else
    echo -e "  ${YELLOW}⏭ Scoring skipped (--skip-scoring)${NC}"
  fi

  echo ""
  echo -e "${BLUE}▶ STAGE 4 — Compose & Deliver SOD${NC}"
  if [ "$PREVIEW" = true ]; then
    python scripts/compose_sod.py --preview
  elif [ -n "$CHANNELS" ]; then
    python scripts/compose_sod.py --channels $CHANNELS
  else
    python scripts/compose_sod.py
  fi

# ── EOD Pipeline ─────────────────────────────────────────────────────────────
elif [ "$MODE" = "eod" ]; then

  echo -e "${BLUE}▶ STAGE 1 — Fetch Slack Digest${NC}"
  if [ -n "${SMARTDIGEST_SLACK_BOT_TOKEN:-}" ]; then
    python scripts/fetch_slack.py --hours 12 && echo -e "  ${GREEN}✅ Slack fetched${NC}" || echo -e "  ${RED}⚠️  Slack failed${NC}"
  else
    echo -e "  ${YELLOW}⏭ Slack: SMARTDIGEST_SLACK_BOT_TOKEN not set${NC}"
  fi

  [ "$DRY_RUN" = true ] && { echo -e "${GREEN}[dry-run] Done.${NC}"; exit 0; }

  echo ""
  echo -e "${BLUE}▶ STAGE 2 — Compose & Deliver EOD${NC}"
  if [ "$PREVIEW" = true ]; then
    python scripts/compose_eod.py --preview
  elif [ -n "$CHANNELS" ]; then
    python scripts/compose_eod.py --channels $CHANNELS
  else
    python scripts/compose_eod.py
  fi
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  SmartDigest ${MODE^^} complete! ✅               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
