# Deal Scanner Architecture: High-Level Design (HLD) & Low-Level Design (LLD)

## 1. System Overview

A modular, highly optimized deal hunter and scanner designed to discover steep discounts on select footwear/apparel brands across Indian e-commerce platforms (Flipkart, Myntra, TataCLiQ). It solves traditional web scraper pitfalls:
1. **Dynamic pricing bypass**: Extracts authenticated VIP/Plus and bank offer discounts ("WOW Deals") embedded in SSR JSON states (`__INITIAL_STATE__`).
2. **Accurate size verification**: Hydrates in-stock variants from size-matrix widgets, filtering out phantom or out-of-stock listings.
3. **Targeted two-phase scraping**: Avoids mass PDP scraping bans by listing in bulk, filtering candidates, and enriching only qualified matches.

---

## 2. High-Level Design (HLD)

### 2.1 Architecture Diagram

```mermaid
flowchart TD
    subgraph Config & State
        CFG["config.json\n(Root filters, Per-query overrides, Cookies)"]
        SEEN["seen_deals.json\n(De-duplication store)"]
    end

    subgraph Ingestion & Scraping Engine
        PL["pipeline.py\n(Orchestrator)"]
        FS["FlipkartScraper\n(scrapers/flipkart.py)"]
        MS["MyntraScraper\n(scrapers/myntra.py)"]
        TS["TataCliqScraper\n(scrapers/tatacliq.py)"]
        HC["HTTP Client Pool\n(Keep-Alive, SSL bypass, Cookies)"]
    end

    subgraph Data Processing & Enrichment
        SRP_P["Phase 1: Search Listing Parse\n(40 items/query + mweb WOW hints)"]
        PRE_F["Phase 2: Pre-Filter\n(Brand, Min/Max Price, Min Disc)"]
        PDP_E["Phase 3: Targeted PDP Hydration\n(Accurate Sizes + Exact WOW Deals)"]
        POST_F["Phase 4: Strict Watchlist Filter\n(Target Size intersection)"]
        DEDUP["Phase 5: Deduplication\n(against seen_deals.json)"]
    end

    subgraph Output & Alerting
        RICH["Rich Terminal UI\n(Formatted Table with WOW Disc %)"]
        MAC_NOTIF["macOS Notification\n(osascript alert)"]
        TG["Telegram Bot Webhook\n(Markdown message)"]
    end

    CFG --> PL
    PL --> FS & MS & TS
    FS --> HC
    HC --> SRP_P
    SRP_P --> PRE_F
    PRE_F -->|Qualified Matches| PDP_E
    PDP_E --> POST_F
    POST_F --> DEDUP
    SEEN <--> DEDUP
    DEDUP --> RICH
    DEDUP --> MAC_NOTIF & TG
```

### 2.2 Core Component Responsibilities

| Component | Responsibility |
| :--- | :--- |
| **`pipeline.py`** | Execution orchestrator. Handles CLI args, merges configuration overrides, executes scrapers, drives the 2-phase pipeline, renders tables, and dispatches alerts. |
| **`scrapers/base.py`** | Core domain model ([`Deal`](file:///Users/prabhashishsingh/codex/deal_scrapper/scrapers/base.py)) and abstract contract ([`BaseScraper`](file:///Users/prabhashishsingh/codex/deal_scrapper/scrapers/base.py)). |
| **`scrapers/flipkart.py`** | Dual-strategy scraper (Desktop DOM + mweb SSR JSON + PDP `multiWidgetState` parser) with connection pooling and session cookie injection. |
| **`scrapers/http_client.py`** | Client factory providing persistent HTTP/2 connection pooling, browser impersonation headers, and platform-specific SSL cert fixes. |
| **`seen_deals.json`** | Local persistent set of unique compound IDs (`{source}::{clean_url}`) ensuring users receive alerts at most once per product. |

---

## 3. Low-Level Design (LLD)

### 3.1 Domain Model & Class Diagram

```mermaid
classDiagram
    class BaseScraper {
        <<abstract>>
        +str name
        +scrape(query: str) list[Deal]*
    }

    class Deal {
        +str title
        +str brand
        +float original_price
        +float sale_price
        +float discount_pct
        +list[str] available_sizes
        +str product_url
        +str source
        +str image_url
        +float? wow_price
        +float? wow_discount_pct
        +str deal_id
    }

    class FlipkartScraper {
        +float delay
        +int timeout
        +int max_retries
        +bool fetch_wow
        +str cookies
        -dict _clients
        +scrape(query: str) list[Deal]
        +enrich_deal(deal: Deal) bool
        -_get_client(ua: str) httpx.Client
        -_fetch(url: str, ua: str) str?
        -_parse_desktop(html: str) tuple
        -_parse_mweb(html: str) tuple
        -_extract_sizes_from_card(card) list[str]
    }

    class Pipeline {
        +load_config() dict
        +load_seen() set[str]
        +save_seen(seen: set[str]) void
        +passes_watchlist(deal: Deal, cfg: dict, overrides: dict) bool
        +build_scrapers(cfg: dict, names: list) list[BaseScraper]
        +run(queries: list, names: list, dry_run: bool) void
        +print_table(deals: list[Deal], target_sizes: set) void
    }

    BaseScraper <|-- FlipkartScraper
    FlipkartScraper ..> Deal : produces & enriches
    Pipeline ..> BaseScraper : orchestrates
    Pipeline ..> Deal : filters & displays
```

### 3.2 Data Contract: `Deal` Entity

Located in [`scrapers/base.py`](file:///Users/prabhashishsingh/codex/deal_scrapper/scrapers/base.py):

```python
@dataclass
class Deal:
    title: str
    brand: str
    original_price: float           # MRP (strike-through price)
    sale_price: float               # Standard discounted selling price
    discount_pct: float             # Standard discount: (MRP - sale_price) / MRP
    available_sizes: list[str]      # Verified in-stock size tokens (e.g. ['9', '10'])
    product_url: str                # Normalized URL without tracking params
    source: str                     # "flipkart" | "myntra" | "tatacliq"
    image_url: Optional[str] = None
    wow_price: Optional[float] = None          # Effective price after auto bank/VIP offers
    wow_discount_pct: Optional[float] = None   # Discount based on wow_price vs MRP

    @property
    def deal_id(self) -> str:
        return f"{self.source}::{self.product_url}"
```

---

## 4. Scraping & Reverse-Engineering Strategies

### 4.1 Two-Phase Execution Pipeline

Flipkart search pages paginate with 40 products per desktop request, but **do not render size selectors or final bank-offer discounts in static HTML card markup**.

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant F as FlipkartScraper
    participant FK as Flipkart Web API

    Note over P,FK: Phase 1: Search Result Scrape
    P->>F: scrape("adidas originals shoes")
    F->>FK: GET /search?q=... (Desktop UA + Cookies)
    FK-->>F: Desktop HTML (40 cards)
    F->>F: Parse Brand, Title, MRP, Sale Price
    F->>FK: GET /search?q=... (Mobile UA + Cookies)
    FK-->>F: mweb HTML (contains __INITIAL_STATE__)
    F->>F: Extract SRP WOW hints & single-variant sizes
    F-->>P: Return 40 raw Deal objects

    Note over P,FK: Phase 2: Pre-Filter & Targeted PDP Enrichment
    loop For each deal
        P->>P: passes_watchlist(deal) [checks sale_price & base discount]
        alt Deal passes price band & discount threshold
            P->>F: enrich_deal(deal)
            F->>FK: GET /product-pdp (Desktop UA + Session Cookies)
            FK-->>F: PDP HTML (contains __INITIAL_STATE__)
            F->>F: Parse size-selector-view_0 (filter OutOfStock)
            F->>F: Parse ATLAS_NEP_V2 (extract exact WOW Deal price)
            F-->>P: Deal updated with real sizes & WOW price
            P->>P: Re-evaluate passes_watchlist(deal) [strict size match]
        end
    end
```

### 4.2 Internal State Parsing (`window.__INITIAL_STATE__`)

Flipkart uses a React/Redux SSR pipeline embedding state into `window.__INITIAL_STATE__ = { multiWidgetState: ... }`. The scraper directly decodes this JSON blob instead of running slow headless browser engines:

1. **In-Stock Size Matrix (`size-selector-view_0`)**:
   - Location: `multiWidgetState.widgetsData.slots[].slotData.widget.data.dlsData['size-selector-view_0']`
   - Path: `scrollToListData_0.value[]`
   - Attributes:
     - `tracking.contentTitle`: Size label (e.g. `"9"`, `"10"`)
     - `tracking.contentType`: Variant status (`"InStock:Variant"`, `"Scarcity:Variant"`, `"OutOfStock:Variant"`)
   - **Filter Logic**: Rejects `"OutOfStock:Variant"`. Only retains available stock.

2. **WOW Deal Pricing (`ATLAS_NEP_V2`)**:
   - Location: `multiWidgetState.widgetsData.slots[].slotData.widget.data` where `type == "ATLAS_NEP_V2"`
   - Extraction: Regex match on `collapseTitle` (e.g. `"Buy at ₹3,671"` or `"Buy at ₹6,264"`).
   - Fallback: `nepContext` JSON field (`fkap` / `fkfp`).

3. **Session Authentication & VIP/Plus Pricing**:
   - Flipkart serves custom tier pricing (Flipkart VIP, Flipkart Plus, personalized bank cards) when authenticating via request headers.
   - Injecting `"flipkart_cookies"` (containing `T=...`, `at=...`, `SN=...`) into the HTTP client headers causes the SSR renderer to emit the lower authenticated rates.

---

## 5. Configuration & Overrides Hierarchy

Configuration values resolve using hierarchical precedence:

```mermaid
graph TD
    Q_OVR["1. Query-Level Override\nsearch_queries[i] (e.g. min_discount_pct=50)"]
    ROOT["2. Root-Level Config\nconfig.json (e.g. min_discount_pct=30)"]
    WL["3. Watchlist Fallback\nconfig.watchlist (Legacy compatibility)"]
    DEF["4. Engine Defaults\n(0% disc, inf max_price, 0 min_price)"]

    Q_OVR -->|Overrides| ROOT
    ROOT -->|Overrides| WL
    WL -->|Overrides| DEF
```

### Evaluation Logic in `passes_watchlist`:

```python
# Priority: Query override -> Root level -> Watchlist -> Engine default
min_disc  = ovr.get("min_discount_pct", cfg.get("min_discount_pct", wl.get("min_discount_pct", 0)))
max_price = ovr.get("max_price", cfg.get("max_price", wl.get("max_price", float("inf"))))
min_price = ovr.get("min_price", cfg.get("min_price", wl.get("min_price", 0)))

# Filter criteria:
1. deal.sale_price >= min_price
2. deal.sale_price <= max_price
3. deal.discount_pct >= min_disc (evaluated on base selling price)
4. deal.brand in target_brands
5. target_sizes.intersection(deal.available_sizes) is not empty
```

---

## 6. Output & Notification Pipeline

The display engine formats all attributes into a multi-column Rich table:
- **`Sale`**: Standard discounted selling price.
- **`Disc %`**: Selling discount vs MRP.
- **`WOW`**: Final effective price after auto-applied bank/VIP discounts.
- **`WOW Disc`**: Effective total discount vs MRP using the WOW price.
- **`Sizes ✓`**: Highlighted target sizes in green, unavailable/adjacent sizes in dim grey.

New deals trigger alerts via:
1. **macOS Notification**: Native popup using `osascript -e 'display notification ...'`.
2. **Telegram Bot**: HTTP POST to `https://api.telegram.org/bot<token>/sendMessage` with Markdown-formatted payload.
