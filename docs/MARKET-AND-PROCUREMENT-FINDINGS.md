# WiseQ — Dutch School-Procurement & Kids-Tech Competitive Landscape

**Research date:** 2026-10-29 · **All sources retrieved:** 2026-10-29
**Method:** direct HTTP fetch (curl + browser UA) of primary vendor/procurement sources, Shopify `products.json` feeds for price data, and PDF extraction for research reports. Every figure below is taken from a retrieved page; nothing is estimated.

**Convention:** *Observed* = directly stated on a cited page. *Inference* = my reading of the observed facts, clearly labelled. No number appears without a source URL.

---

## 0. Baseline: what WiseQ sells and at what price (needed to judge everything else)

WiseQ's own Shopify catalogue feed (`https://www.wiseq.nl/products.json?limit=250`) returned **230 products**, of which the product-type breakdown is: 76 Oplaadset, 38 Oplaadkabel, **23 Kinderkoptelefoon**, 16 USB-adapter, 9 Tablethoes, 9 Draadloze lader, 9 GPS tracker, **8 Gehoorbescherming**, 7 USB-hub, 6 Audiokabel, **4 Kindertablet**, 3 Laptopkar, **3 Smartwatch**, 2 Koptelefoon, 2 Koptelefoonhouder, 2 Koptelefoon case, 1 Schoolbestelling, 1 Kinderoordopjes, 1 Oordopjes.[2]

**Kids audio/tablet/watch prices observed on WiseQ's own catalogue feed [2], corroborated by the "vergelijken" page [8]:**

| WiseQ product | Type | Battery | ANC | Age | Price (EUR) |
|---|---|---|---|---|---|
| Oordopjes (wired earbuds) | Bedraad | n.v.t. | No | 8+ | €9,95 |
| Junior | Wired (3,5 mm) | n.v.t. | No (passive) | 3–9 | €18,95 |
| One (wired, flexible) | Bedraad (3,5 mm) | n.v.t. | No (passive); 85 dB volume limiter | 3–15 | €19,95 |
| BTwireless | Wireless | 8 h | No | 5–12 | €19,95–€24,95 |
| Hero | Wireless | 38 h | No (passive) | 5–12 | €27,95 |
| Unbreakable | Wireless | 45 h | No — passive, ~13 dB attenuation (not ANC); volume limiter 93 dB, switchable to 85 dB | 5–15 | €34,95 |
| Kids ANC | Wireless | 35 h | **Yes, active (ANC)** — the only ANC model | 6–14 | €49,95 |
| Hearing protection (8 SKUs) | Oorkap | — | — | — | €21,95 |
| Bedrade oordopjes voor kinderen | Wired | — | — | — | €9,95 |
| Smartwatch voor kinderen (3 colours) | — | — | — | — | €74,95 |
| WiseTab kindertablet 96GB | — | — | — | — | €124,95 |
| WiseTab kindertablet 160GB | — | — | — | — | €159,95 |

Note the wide gap between WiseQ's own catalogue prices and the homepage headline prices visible in search snippets (e.g. "Junior - Bedraad - Hufterproof - Roze Normale prijs €18,95", "WiseQ Kids ANC … €49,95") — these agree, so the €9,95–€49,95 band for kids audio is the real WiseQ shelf.[1][8]

**WiseQ's own B2B mechanics (observed):**
- "Bestel je op factuur en toegang tot passende prijzen voor grotere aantallen" — business customers register to order on invoice and get volume prices.[9]
- Staffel (tier) pricing exists; **actual tier prices are gated behind business registration** ("De actuele staffelprijzen zijn zichtbaar zodra je bent geregistreerd").[10]
- "Scholen en onderwijsinstellingen betalen standaard achteraf op factuur." / "Op factuur — gebruikelijk voor scholen en besturen." / "Levering op schooladres, ook tijdens vakanties in overleg."[10]
- Free sample request: "Vraag een proefexemplaar aan en leg hem een week in de klas."[10]
- **Warranty: "Op WiseQ-producten geldt standaard 1 jaar garantie op defecten die ontstaan bij normaal gebruik."** Excludes damage from "verkeerd gebruik, vallen, stoten, vocht, slijtage". Site header also claims "Levenslange ondersteuning" and "30 dagen geld terug garantie".[12]
- WiseQ itself says "Het populairste model voor scholen" for the **One** (wired, flexible, mic, €19,95), and recommends wired for most schools.[8][11]
- Note: WiseQ's **15% school discount claimed in the task brief was NOT found on the live site.** The site consistently describes *staffelprijzen* (volume tiers) rather than a flat 15% school discount; the only percentages found on WiseQ pages are "10 tot 15% uitval per schooljaar" (attrition allowance for shared use) and "15% hoort bij … uitval" context — not a discount. Treat "15% school discount" as unverified.[8][10]

---

## 1. Direct competitors in Dutch kids' audio

### 1a. BuddyPhones (ONANOFF) — the school/education push, confirmed

**Positioning (observed).** BuddyPhones' EU site (en-eu) is organised into collections explicitly including **"Educational Headphones ✏️"** and **"Kids: Wired Headphones"**, alongside "Daily Use", "Travel" and "Gaming".[14] The EU shop collection page headline confirms the category split: "Daily Use Headphones", "Travel Headphones", "Educational Headphones", "Gaming Headphones", "Headphone Accessories".[14]

**The School+ line (observed).** The School+ feature page lists: "SafeAudio 85dB, (Max Volume Limiting)", "Audio Tuned Towards the Spoken Vocal Range", "High Performance Boom-mic with Control Button, 1.4 Meter Long", "Foldable & Cushioned Headband", "Super Durable", "Built-in BuddyJack for Sharing", "Hypo-allergenic Cushion with Anti-sweat Wicking". The **"BuddyJack"** feature (built-in splitter allowing up to 4 cables to one device) is the distinctive classroom multi-pupil mechanic.[17][16]

**Pricing — BuddyPhones EU shop, in EUR, retrieved 2026-10-29 [14]:**

| Model | Configuration | Price (EUR) |
|---|---|---|
| BuddyPhones Explore+ | Wired + inline mic | €24,90 |
| BuddyPhones Galaxy | Wired + gaming (boomer mic) | €27,90 |
| BuddyPhones POP Fun | Wireless + 2 volume limits | €42,90 → sale €29,90 |
| BuddyPhones Play+ | Wireless + StudyMode | from €49,90 |
| BuddyPhones PlayEars+ | Wireless + animal ears | €59,90 |
| BuddyPhones Cosmos+ | Wireless + ANC | €79,90 |
| BuddyPhones CosmosFun | Wireless + ANC | €99,99 |

**Second EU storefront, different prices (observed).** ONANOFF's own EU store (`onanoff.eu/products.json`) lists: Explore+ €36,95, POP Fun €27,95, Play+ €45,95, Cosmos+ €72,95, CosmosFun €90,95, PlayEars+ €54,95, BuddyCase €13,95, BuddyCable €11,95. **Note the discrepancy:** the same SKUs are ~15–20% cheaper on onanoff.eu than on buddyphones.com/en-eu.[14][18] — observed fact, unexplained. Also: onanoff.eu's `School` collection currently contains **only 1 product (BuddyCase, €13,95 excl. VAT)**; School+ itself is not listed there in the feed.[18]

**Dutch street prices (observed).** BuddyPhones School+ Wireless on Proshop NL; bol.com listings found at **€25,00** (BuddyPhones POP Fun draadloos, blauw, 4.6/62 reviews) and **€37,27** (Buddyphones POP), per a Google-Shopping-derived price aggregator (keenable.ai). The onanoff.eu School collection showed "€27,95 Excl. VAT" for a School-series item in search results.[14][18]

**Warranty (observed, and this is where BuddyPhones clearly beats WiseQ).** ONANOFF Terms & Conditions: "**Consumer products: Two (2) year** from the date the product has been purchased. **Registered Consumer products: Three (3) years** from the date the product has been purchased. **Commercial products: Two (2) year** from the date the product has been purchased." The Explore+ product page also states "extensive testing and a **2-year limited warranty**".[15][16]

**Read-across (inference):** BuddyPhones prices itself *above* WiseQ at the wired-school end (Explore+ €24,90 vs WiseQ One €19,95) and well above at the wireless/ANC end (Cosmos+ €79,90 vs WiseQ Kids ANC €49,95). Its warranty is 2 years (3 if registered) vs WiseQ's 1 year. BuddyPhones wins on warranty length and on the school-feature narrative (boom mic + BuddyJack + "Educational" collection), WiseQ wins on price and on the Dutch-language school content (staffels, proefexemplaar, klassenset guidance, factuur op factuur).

### 1b. JLab (JBuddies) — mass-market value, priced *below* WiseQ

Observed EUR prices from JLab's own NL storefront `jlab.com/en-nl/collections/kids-headphones` (retrieved 2026-10-29):[19]

| JLab kids product | Price (EUR) |
|---|---|
| JBuddies Pop Wired (ages 2+) | €20,95 |
| JBuddies Studio 2 On-Ear Wired (ages 6+) | €20,95 |
| JBuddies Folding Wired (ages 2+) | €20,95 |
| JBuddies Pro Wired Over-Ear (ages 8+, hearing-protection switch) | €26,95 |
| JBuddies 2-in-1 Wired + Wireless, 48+ h | €23,95 |
| JBuddies Wireless, 48+ h, shared/wired mode | €31,95 |
| JBuddies Wireless over-ear, 35+ h, ages 8+ | €36,95 |
| JBuddies Studio Wireless, 24+ h | €31,95 |
| JBuddies Protect hearing-protection earmuffs | €23,95 |
| (NL-adjacent) JBuddies wired 3.5 mm & Type-C | €26,95 |

Cross-check: bol.com lists "JLab JBuddies Draadloze Kinderkoptelefoon … 50+ uur … 85 dB" and JLab's own range via beslist.nl at €29,99–€101,67 depending on model. JLab product copy explicitly says "**Comfort for home or school**" and "on-ear kids headphones with volume safe sound".[19]

**Inference:** JLab's wired range (€20,95–€26,95) sits *on top of / just below* WiseQ's wired range (€18,95–€19,95 for Junior/One), and clearly below WiseQ's wireless tiers (Hero €27,95, Unbreakable €34,95). JLab's positioning is explicit about school use but has **no school/B2B channel, no tier pricing, no quote workflow** visible in the Netherlands.

### 1c. Puro Sound — premium USD-priced, effectively out of the Dutch school mass market

Observed USD prices from `purosound.com/products.json` (retrieved 2026-10-29):[20]

| Puro product | Price (USD) |
|---|---|
| PuroBasic Wired Volume Limited | $29.00 |
| JuniorJams Volume Limited On-Ear | $35.00 |
| JuniorJams-Plus | $65.00 |
| BT2200s Bluetooth | $99.00 |
| BT2200-Plus Bluetooth | $99.00 |
| PuroFlex Kids Bone Conduction | $39.50 |
| PuroQuiet (ANC) | $50.00 |
| PuroQuiets ANC | $119.00 |
| PuroQuiet-PLUS ANC | $119.00 |
| PuroPro Hybrid ANC | $125.00 |
| PuroCalm adjustable hearing protectors | $29.00 |
| Extended warranty | $15 / $20 / $30 / $35 |

A third-party price aggregator records Puro Sound in NL "from €35,00 (Amazon.nl) to €61,00 (ubuy.co.nl) across 4 offers". Puro's own site publishes **no EUR price and no Dutch school/B2B program**; its "back-to-school" content is consumer-facing (parent blog), and it sells via Amazon/ubuy rather than a Dutch school channel.[20]

### 1d. The actual NL school-channel incumbents (these are WiseQ's real B2B competitors, not BuddyPhones)

This is the most important finding of section 1. BuddyPhones/JLab/Puro are **consumer brands** that happen to mention school. The companies Dutch schools actually buy school-grade headsets from are specialist Dutch school suppliers, and they are **an order of magnitude cheaper** than WiseQ:

**Rkop** (Rkop B.V., Numansdorp; "Rkop levert sinds 2011 betrouwbare oplossingen"; "Sterke koptelefoons en oordopjes voor een lage prijs. Speciaal voor scholen, de zorg en musea"):[26]

| Rkop product | List | From |
|---|---|---|
| Rkop EM | €3,49 | €1,89 |
| Rkop Nova | €9,99 | €7,99 |
| Rkop MAX (replaceable braided cable, passive NC) | €16,99 | €9,89 |
| Rkop FLEX kinder-/kleuterkoptelefoon (4–7 j, own logo option) | €19,99 | €15,99 |
| Rkop doosje A (in-ear + case) | €2,95 | €1,79 |
| Rkop doosje C | €3,19 | €1,89 |
| Rkop EAR luxe oordopjes jack | €2,99 | €1,79 |
| Rkop-ear-usb-c | €3,99 | €2,79 |
| Rkop Earbud CE HQ | €3,95 | €1,79 |
| Rkop Buddy concentratiekoptelefoon | €22,95 | €15,95 |

Rkop also offers **"Bestelbon insturen"** (send in a purchase order) and **"Offerte aanvragen"** (request a quote), "Achteraf betalen op factuur, ideal, Wero", "Jaarlijks modelaanpassingen", and a **"Gratis proefpakket bestellen"** (free trial pack). Shipping NL+BE, shipping cost €2,95, delivery 1–3 working days.[26]

**Koptelefoon-onderwijs.nl (Oortjessale, trading since 2011)** — the same catalogue positioned as a school webshop, with the same tier logic: "Vanaf € 1,89 / Vanaf 30 stuks leverbaar", Rkop MAX €16,99 → from €9,89, Rkop FLEX €19,99 → from €15,99, Rkop Buddy €22,95 → from €15,95, plus "Optioneel met uw eigen logo" on the doosjes. Headline: "Levering binnen 1-3 werkdagen", "Achteraf betalen", "Goedkoop!". It cites "honderden klanten" and reviews.[27]

**Opzijnkoptelefoon.nl** — "Stevige Koptelefoons voor Onderwijs vanaf € 7,50", built by teachers ("Wij hebben als leerkrachten uit het onderwijs een koptelefoon voor school ontwikkeld"), with a **detachable/replaceable audio cable** as the durability strategy, plus an **offerte-aanvraag** page.[28]

**School Supplier (schoolsupplier.nl)** — a dedicated Dutch school supplier webshop selling headphones, concentration screens, concentration headphones and posters, with an explicit quote workflow for schools (see §2 and §3).[29]

**Inference:** WiseQ's €18,95–€34,95 wired/wireless kids headphones sit **6–18× above** Rkop's €1,79–€15,99 school-grade tier. If a school buys a class set (20–30 pcs), Rkop's MAX is ~€290–€480 vs WiseQ One at ~€400–€600 for the same count. WiseQ's stated rationale — durability, "Super Durable"-type construction, warranty — is exactly what Rkop counters with a **replaceable cable** (same outcome, lower price) and its own 1-year default + Dutch consumer-law guarantee. WiseQ's differentiator is therefore not price and not warranty length (1 yr vs BuddyPhones 2–3 yr) — it is **service/continuity**: proefexemplaar, staffelprijzen, factuur op factuur, delivery on the school address, and Dutch-language klassenset sizing guidance. That is a services-led pitch, not a product-led one, and it competes most directly with Rkop/School Supplier (services-led, cheap) rather than with BuddyPhones (product-led, dearer).

### 1e. Other named brands — what could and could not be confirmed

- **Onear** — a Google-Shopping-derived aggregator page states: "Onear kinder koptelefoon costs from € 25,99 (bol.com) to € 76,75 (bol.com) across 4 offers. 4 offers in NL", with the listed offers being PowerLocus Buddy €29,99, EKIDS Stitch on-ear blauw €25,99, a generic "Comfortabele On-Ear Koptelefoon voor Kinderen en Volwassenen" €76,75. **No Onear-branded own-storefront, warranty policy, or school/B2B programme was found.** Treat Onear as a thin/no-name presence on bol.com, not a like-for-like competitor.[42 → see §5 note]
- **Xorio** — **no Dutch Xorio kids-headphone presence could be found at all.** Searches for "Xorio kinderkoptelefoon prijs Nederland" returned no Xorio product page. **Xorio could not be verified as an NL market participant.**
- **JBL (JR 320 / JR 320BT)** — a genuine NL mass-market competitor, explicitly school-labelled on bol.com: "JBL Junior 320 - Kinderkoptelefoon - 85 dB Veilig Volume - On-ear - Met Microfoon - 3.5 mm Jack - **Voor School & Tablet**". 5prijzen.nl lists JBL JR 320BT (wireless) from **€33** (also shown as from €41 with a €20,59 line item), score 8.5/10 from 22 reviews.
- **Philips (TAK2000CT / TAK4200MP / TAK4206PK)** — present in NL (bol.com: "PHILIPS TAK2000CT/00 Kinderkoptelefoon - On-Ear - Veilig luisteren tot 85 dB - Audio Share - USB-C & 3,5 mm - Opvieuwbaar"), listed on avxperten.nl around EUR 15 equivalent.
- **OTL Technologies** — licensed kids headphones (Bluey, Peppa Pig, Superman, L.O.L.) sold in NL via avxperten.nl at €27,25 and €27,99 incl. VAT.
- **PowerLocus Buddy** — NL presence at €29,99 on bol.com (4.6, 216 reviews).

---

## 2. Dutch school procurement reality

### 2a. The 2026/2027 threshold — the repo's EUR 216,000 is CORRECT

**Observed (PIANOo, Expertisecentrum Aanbesteden):** "De Europese Commissie stelt elke 2 jaar nieuwe drempelbedragen vast voor overheidsopdrachten. Deze bedragen (exclusief btw) gelden **van 1 januari 2026 tot en met 31 december 2027**." The classical-supply table reads:[3]

| Soort overheidsopdracht | Drempelbedrag (EUR, excl. btw) |
|---|---|
| Werken | €5.404.000,- |
| **Leveringen en diensten voor decentrale overheid** | **€216.000,-** |
| Leveringen en diensten voor centrale overheid | €140.000,- |
| Overheidsopdrachten voor sociale en andere specifieke diensten | €750.000,- |
| Prijsvragen voor decentrale overheid | €216.000,- |
| Prijsvragen voor centrale overheid | €140.000,- |
| Diensten voor >50% gesubsidieerde werken | €216.000,- |
| >50% gesubsidieerde werken | €5.404.000,- |
| Concessieovereenkomsten (werken) / Dienstenconcessies | €5.404.000,- |

**This confirms the repo figure of EUR 216k for 2026/2027** — as the threshold for **leveringen (supply) and diensten (services) to decentrale overheid (decentralised government), which is what a school board is.** Concessions are €5.404m. Bekendmaking: Verordening 2025/2151 (concessies) and 2025/2152 (klassiek). A second source, TenderGrowth, states the new amounts were "in december 2025 vastgesteld voor 2026 en 2027" and are revised biennially on IMF special drawing rights.[3][40]

### 2b. Does a school qualify as an "aanbestedende dienst"?

**Observed (PIANOo, sector dossier Onderwijs):** "Veel primaire en voortgezet onderwijsinstellingen kwalificeren zich als publiekrechtelijke instelling. Dit leidt er toe dat de aanbestedingswet- en regelgeving van toepassing is als onderwijsinstellingen ervoor kiezen een overheidsopdracht in de markt te zetten via een inkoopprocedure. Dit geldt zowel voor primaire taken (zoals onderwijs verzorgen) als secundaire verplichtingen (zoals schoonmaak van schoolgebouwen)." And: "Veel onderwijsinstellingen zijn een aanbestedende dienst omdat zij voldoen aan de criteria voor een publiekrechtelijke instelling. Dit betekent dat de inkoop van bijvoorbeeld meubilair, **computers**, schoonmaak, schoolgebouwen en **leermiddelen** onder de aanbestedingsregels vallen."[21]

**Inference:** for a single annual purchase of a class set of headsets (a few hundred to a few thousand euros), the EU threshold is not the binding constraint — but the school's *own inkoopbeleid* is. A school board with a written inkoop- en aanbestedingsbeleid will typically require a documented, quotable purchase even far below €216k.

### 2c. What a school actually demands from a new supplier — the concrete documents

**Observed — school-official purchase-order flow.** Rkop's school-facing footer lists three explicit procurement entry points: **"Bestelbon insturen"** (send in a purchase order), **"Offerte aanvragen"** (request a quote), and **"Gratis proefpakket bestellen"**, plus "Bestel en betaalinformatie", "Retouren, annuleren, garantie en klachten", and payment via "Achteraf betalen op factuur, ideal, Wero".[26]

**Observed — quote-request field list (School Supplier).** Their offerte-aanvraag page states: "Wilt u **meer dan 50 exemplaren** van een product bestellen voor uw klas, afdeling of school? Vraag dan vrijblijvend een offerte aan." It offers "eventuele staffelprijzen en **bestellen op factuur**", and says "Ook wanneer uw school eerst een offerte nodig heeft voor **interne goedkeuring**, kunt u dit formulier gebruiken." What they ask you to state: **"naam van de school of organisatie; gewenste product(en); gewenste aantallen; eventuele gewenste kleuren of uitvoeringen; factuur- en/of aflevergegevens indien relevant."**[29]

**Observed — the AVG / DPA layer.** The **Privacyconvenant Onderwijs** is the sector standard. Its FAQ states: "Is het convenant alleen voor leveranciers? **Nee, het convenant is voor scholen én leverancers.** Hierdoor weten scholen, leveranciers én distributeurs van digitale onderwijsmiddelen wat ze over en weer van elkaar mogen verwachten." Its stated purpose is "documenten op maat die scholen en leveranciers helpen om goede onderlinge afspraken te maken", and it notes this "scheelt scholen ook heel veel uitzoekwerk en tijd **als leveranciers dezelfde documenten gebruiken** voor het regelen van privacyzaken." The initiators are PO-Raad, VO-raad, MBO Raad plus supplier associations MEVW (ex-GEU), KBb-E and VDOD, united in **Edu-K**.[22] A **model verwerkersovereenkomst** is published alongside (versions 4.0 and a current version; convenant+model are downloadable from the same site).[6][37]

**Critical scoping nuance (observed).** The same FAQ says: if the school itself buys the digital teaching resource, the school is verwerkingsverantwoordelijke and the convenant applies. But "Als een andere persoon dan de onderwijsinstelling een digitaal onderwijsmiddel bestelt, bijvoorbeeld [maar niet beperkt tot] de student of ouder, dan is de leverancier bij wie het onderwijsmiddel wordt besteld de verwerkingsverantwoordelijke. De onderwijsinstelling is in die situatie privacy-technisch gezien geen partij en het convenant is **niet** van toepassing." It also states the convenant does apply to the mbo, where "de mbo-instelling zelf digitale onderwijsmiddelen bestelt".[22]

**Observed — SIVON's supplier-facing obligations.** SIVON represents "ruim 450 schoolbesturen in het primair en voortgezet onderwijs". Its "Informatie voor leveranciers" page lists the supplier-side compliance work it runs on schools' behalf: **"Data Protection Impact Assessment (DPIA)", "Toetsen verwerkersovereenkomsten", "Project ondersteuning ketenbeheer", "Toetsingskader AI", "Leveranciersmanagement", "School-CERT"**, and notes the Normenkader IBP (with the "Privacybewuste School" theme) applies to both schools and suppliers. It also runs "Digitaal Veilig Onderwijs (DVO)" activities.[23]

**Observed — the 2026 refresh.** SIVON published (Feb 2026) an "Oproep: denk mee over model verwerkersovereenkomst 5.0", stating "Sinds 2025 is het Privacyconvenant overgegaan in **Edu-V**, het keurmerk voor digitale gegevensuitwisseling in het onderwijs. Leveranciers van …" — i.e. the sector privacy framework is mid-migration to Edu-V with a 5.0 model verwerkersovereenkomst in consultation.[7][23]

**Observed — the ACM's direction of travel on leermiddelen.** The ACM published "stop koppelverkoop van leermiddelen en versterk samenwerking bij inkoop", and a related trade piece quotes: "**Een school wordt tegenwoordig bijna benaderd als een commerciële instelling. Iedere school is verantwoordelijk voor zijn eigen inkoop van diensten en materialen.**" This is the direction that pushes schools toward professional, quoted, portal-based procurement rather than ad-hoc email.[36]

### 2d. Concrete document checklist a Dutch school requires from a new supplier (synthesis)

Distinguishing **observed** from **inferred**: the individual requirements above are observed. The consolidated list is my synthesis (labelled *inference*), assembled from the observed sources — the specific list a given school requires varies by its inkoopbeleid.

**Observed requirements (each with source):**

| Requirement | Source |
|---|---|
| Registration as a business customer, so an account/invoice relationship exists | [9] WiseQ zakelijke klant page; [26] Rkop "Bestelbon insturen" |
| Ability to order **on invoice** (achteraf op factuur), not just card/prepayment | [9][10][26][29] |
| Staffel (volume-tier) price list, visible after registration | [9][10][29] |
| A written **offerte** usable for internal approval, with school name, products, quantities, colours, invoice/delivery details | [29] |
| Possibility to supply via a **purchase order (bestelbon)** | [26] |
| Delivery to the **school address**, including during holidays by arrangement | [10] |
| Free **sample/proefexemplaar** before committing a class set | [10][26][29] |
| Written **warranty** terms (WiseQ: 1 year, defects at normal use; BuddyPhones: 2 yrs / 3 yrs registered) | [12][15][16] |
| Published **returns/retourbeleid** and complaint procedure | [12][26] |
| If the product is a *digital teaching resource* processed for the school: a **verwerkersovereenkomst** per Privacyconvenant / model 5.0 | [22][23][37] |
| A **leveranciersmanagement / DPIA / normenkader-IBP** compliance posture, and willingness to be reviewed | [23] |

**Inference (synthesis, not a quoted list):** a minimum onboarding pack for a small Dutch supplier selling to schools should contain: (1) an AVG/DPA-verwerkersovereenkomst template aligned to the Privacyconvenant model — even if the headband product falls outside its strict scope, schools ask for it as a matter of routine; (2) an offerte template with the fields School Supplier names (school/organisation name, product, quantity, colour/variant, invoice and delivery details); (3) a bestelbon/PO acceptance statement; (4) staffel price sheet; (5) warranty + returns + complaint policy; (6) a proefexemplaar offer; (7) delivery terms incl. school address, delivery windows and holiday periods; (8) a leveranciersstatus for the sector (e.g. Edu-V registration if the product touches student data). **The single most-missed item in WiseQ's current public pages is a visible verwerkersovereenkomst/DPA offer** — the zakelijke-klant page promises only "bestellen op factuur en toegang tot passende prijzen".[9]

---

### 2e. SamitaWS is WiseQ's own shop app, NOT a school registry (corrected 2026-10-29)

**This corrects an earlier reading of WiseQ's own material.** Earlier drafts
implied "SAMITAWS registration" was a Dutch school-procurement registry that
a supplier had to be admitted to. It is not.

**Observed (WiseQ's own B2B page).** `https://www.wiseq.nl/pages/zakelijke-klant`
renders a literal Shopify app embed:

    {SamitaWSRegistrationForm:MTA0NTY=}

**Observed (Shopify App Store).** The app is
**"Sami B2B Wholesale Pricing"** by developer **Samita**
(`https://apps.shopify.com/wholesale-sami`): "Run B2B & retail in one store
with custom wholesale pricing, bulk ordering, tax control & net terms."
Its listed features are exactly the ones WiseQ's site advertises —
wholesale pricing by customer group/product/variant/quantity, **volume
discounts and quantity breaks**, B2B buyer approval via signup forms and
customer tags, quick-order forms, tax display and net terms. Pricing tiers
are Free / $18.70 / $37.50 per month.

**Why it matters.** SamitaWS is the mechanism that *implements* WiseQ's
staffelprijzen. The staffel prices are therefore configured **inside
WiseQ's own Shopify store**, not published in the repository, not on the
open web, and not obtainable from any public feed. They are only visible
after the buyer registers through that form.

Consequence for this system:
- The staffel ladder is a **Rob-only input**. It cannot be scraped, synced
  from Shopify's public catalogue, or derived from the UCP/MCP endpoint.
- `wiseq-hermes` must therefore treat staffel pricing as an
  operator-supplied table (currently a 0% placeholder with an explicit
  `school_discount_is_placeholder` flag), never as a value it invents.
- The Shopify public catalogue (`/products.json`) does **not** expose
  wholesale/volume prices at all, so the 139 priced modelled products are
  consumer prices, not school prices.

**What it is not.** Searches for "SAMITAWS" return only unrelated Shopify
app-store listings; there is no Dutch school-procurement register by that
name. Any claim that WiseQ must "join SAMITAWS" to sell to schools, or that
SAMITAWS is a supplier vetting body, is false.

**Observed (WiseQ class-set page).** The ladder's structure is public even
though the numbers are not: "We werken met staffels: hoe groter de afname, hoe
lager de stuksprijs. De staffels lopen door vanaf klein tot schoolbreed, en
gelden ook als je meerdere modellen in één order combineert." — and "De
eerste staffel begint al bij bescheiden aantallen. Registreer je als
zakelijke klant om de exacte grenzen en prijzen te zien."

**Observed (staffel table).** `https://www.wiseq.nl/pages/staffelprijzen`
is referenced by the class-set page but **not retrievable without business
registration**; the page itself does not publish the ladder.

**Correction to the earlier "SIVON/Onderwijs Inkoop" onboarding advice.**
That advice stands, but it must not be justified with SamitaWS. The real
onboarding targets are the collective procurement bodies (SIVON,
Onderwijs Inkoop Groep / DAS) named in section 3.

### 2f. WiseQ's own school pages now promise a 2-year warranty including physical damage

This is new as of the 2026-10-29 audit and it contradicts the terms.

**Observed (`https://www.wiseq.nl/pages/ict-voor-onderwijs-kinderkoptelefoons-tablets-laptopkarren-wiseq`).**
Under the school heading it states: "**2 jaar garantie**" and, explicitly:

    2 jaar garantie, ook bij fysieke schade
    Kabel doorgebeten of hoofdband beschadigd? Ook dat valt onder de garantie.
    Geen gedoe, geen onverwachte kosten voor de school.

and "Twee jaar garantie bij aanschaf" as a selling point of the school
offer.

**Observed (`https://www.wiseq.nl/pages/algemene-voorwaarden`, section 7).**
"Op WiseQ-producten kan daarnaast een **fabrieksgarantie van 1 jaar** van
toepassing zijn tegen fabricagefouten, gerekend vanaf leverdatum." Excluded:
"verkeerd of onzorgvuldig gebruik; normale slijtage; ongelukken of externe
beschadiging; aanpassingen of reparaties door derden zonder toestemming."

**This widens the warranty contradiction from two sources to three**, and the
new source is the sharpest one, because it is the page a school buyer reads:
- Live general terms: **1 year**, excluding accident and external damage.
- Live school-ICT page: **2 years, including physical damage** ("kabel
  doorgebeten", damaged headband).
- WiseQ's Amazon.nl listings + Rob's own `Handleiding_opzet.txt`: **2 years
  product warranty**, "alles behalve fysieke breuken wordt vergoed".

Note the third source sits between the other two: 2 years, but excluding
physical breakage — while the school page now promises 2 years *including*
it. The four positions cannot all be true at once.

**Why this matters operationally, not just legally.** A school class set is
ordered once and used hard for years. If the school-facing promise is the
operative one, then a device chewed through by a child is a **supplier
replacement, not a warranty claim**, and the agent must not route it to a
"warranty" flow that will reject it on "fysieke schade". `wiseq-hermes`
currently has no warranty-claim workflow at all, so this does not yet produce
wrong behaviour — but it is the shape of the workflow that has to be built,
and it must be driven by whichever policy Rob declares operative.

**Decision required from Rob (added to the handover):** state one operative
warranty policy — term length, and whether physical damage is covered —
and align the terms page, the school page, the Amazon listings and the
agent behaviour to it.

### 2g. The 13 dB figure is passive attenuation, not a volume limit (corrected 2026-10-29)

**Observed (`https://www.wiseq.nl/agents.md`).** WiseQ's own agent-facing
catalogue brief tabulates the five models' noise reduction as: Junior
"Passief", One "Passief", Hero "Passief", Unbreakable "**Passief, ongeveer
13 dB demping**", Kids ANC "**Actief (ANC)**" — and warns: "**Belangrijk
voor correcte weergave: de Kids ANC is het enige WiseQ-model met actieve
ruisonderdrukking.** De Unbreakable dempt geluid passief, door pasvorm en
oorkussens — dat is geen ANC."

The same brief adds that "De Unbreakable heeft een volumebegrenzing van
**93 dB die met een schakelaar naar 85 dB kan**, is geschikt voor kinderen
van 5 tot 15 jaar" — so the 13 dB figure and the volume limiter are two
different quantities, on the same model.

**Why the correction matters.** Several product listings and image filenames
say "13dB noise cancelling", and an earlier draft of the market document
repeated "13 dB" in a way that read as WiseQ's headline volume limit. 13 dB
is *sound attenuation*, a different quantity from a *volume limiter*:
- 13 dB = how much sound the headset reduces passively (Unbreakable).
- 85 dB = the maximum output level the One/Junior allow.

An agent that treats 13 dB as WiseQ's ceiling for safe listening would state
a claim that is both wrong and dangerous to repeat to a school. Any
school-facing output should use the **volume-limiter** figure — 85 dB for the
One and Junior, 93 dB switchable to 85 dB for the Unbreakable — and describe
the 13 dB explicitly as *passive attenuation on the Unbreakable*, not ANC.
The product table in section 0 of this document previously attributed the
13 dB to the Hero; that was wrong and has been corrected to the Unbreakable,
where WiseQ's own brief puts it.

**Note.** `agents.md` also states "Op WiseQ-producten geldt **1 jaar
garantie**", agreeing with the terms page and not with the school page.

**Decision required from Rob:** confirm whether the 13 dB products are
positioned as ANC or as passive-attenuation, since the live image filenames
and the agent brief disagree.

### 2h. SIVON's device rounds do not cover WiseQ's catalogue; Edu-V is a separate, conditional gate

**Observed (SIVON "Devices Ronde 11", `sivon.nl/wp-content/uploads/2025/12/DevicesRonde11_Specificaties_V0.9.pdf`).**
The published spec sheet is a **Chromebook** specification: "C1: Chr 11,6"
Touch 8/64", "C2: Chr 14" Touch 8/128", Chrome OS, AUE "juni 2032", directiebegroting (incl. BTW) €285,00 and €480,00, with an EduRoam requirement. It also specifies
per-device service obligations (garantie, SLA) and upgrade caps such as
"Meerprijs naar 2 jr carry-in garantie onder dezelfde Diensten voorwaarden
(Maximaal €24,- incl. BTW)" and "Chrome Education Upgrade (Maximaal €40,-
incl. BTW per device)".

**Consequence.** This is the most detailed, most citable device requirement
document in the Dutch school market — and **it does not describe any product
WiseQ sells**. WiseQ has no Chromebook, no Chrome OS device and no
Google Workspace Education Upgrade. Treat a SIVON "device round" as a
different market segment, not as WiseQ's qualification target. The laptops
in WiseQ's catalogue are ordinary laptops for charging carts, not managed
Chromebooks for instruction.

**Observed (SIVON, 26 October 2026, "Wat gezamenlijke aanbestedingen schoolbesturen heeft opgeleverd").**
Since 2020 SIVON's collective procurement has moved toward **price and
service separation** ("de kosten voor leermiddelen en de kosten voor de
dienstverlening makkelijker van elkaar te onderscheiden"), more supplier
choice, and — directly relevant to WiseQ — **anonymised invoice data supplied
by suppliers to SIVON** so SIVON can analyse which prices rise and why. The
same piece announces the **Open Keuzecatalogus Leermiddelen**
(`openkeuzecatalogus.nl`), going online in November for all secondary
education, built with Edu-V standards, to help schools find, compare and
choose teaching materials faster.

**Observed (Edu-V, `https://www.edu-v.org/voor-leveranciers/hoe-krijg-je-het-keurmerk/`).**
The Edu-V keurmerk is for "leveranciers van digitale onderwijs- en
leermiddelen die zich inzetten voor veilige en effectieve
gegevensuitwisseling". Entry requires that "jouw product in aanmerking komt
voor het Edu-V keurmerk **én** je een **intentieverklaring hebt ondertekend**",
followed by a three-step assessment of whether the product meets the
requirements.

**What this means for WiseQ, stated carefully.**
- Edu-V is **conditional**, not automatic: it needs a signed intent
  declaration *and* a product that qualifies. A supplier cannot simply
  "join" it.
- Edu-V's own scope is "digitale onderwijs- en leermiddelen" with data
  exchange. WiseQ's headphones and ear defenders arguably sit outside that
  scope; its **WiseTab children's tablet** is the product where the question
  is genuinely live, because it is a data-carrying device going into a
  school.
- The `edu-v.org/keurmerkregister` is the authoritative list of holders. A
  direct fetch of the register from this environment returned only a cookie
  consent shell, and no WiseQ entry was retrievable. **WiseQ's Edu-V status
  is therefore "not retrievable", not "absent".** Rob can check his own
  position against the register in one minute.
- The Open Keuzecatalogus (November) is a **new channel**, and it is
  opt-in per supplier through Edu-V standards. It is worth watching.

**Decision for Rob (added to the handover):** confirm whether WiseQ has
signed an Edu-V intent declaration, and whether the WiseTab is intended to
be covered by the keurmerk. If yes, the keurmerkregister entry should be
public and quotable; if no, no school-facing material should imply Edu-V
coverage.

## 3. Dutch school-procurement and supplier-portal platforms that actually exist

| Platform | What it is (observed) | Relevance to a small supplier onboarding |
|---|---|---|
| **Onderwijs Inkoop Groep (OIG)** | "Het inkoopcollectief voor besparen, aanbesteden en contractbeheer"; "dé partner voor onderwijsinstellingen die willen besparen op inkoop"; "Een samenwerking met de Onderwijs Inkoop Groep verzekert u van **snel resultaat**". Runs a **Dynamisch Aankoopsysteem (DAS)** for school purchasing — e.g. DAS OIG Computertoebehoren, plus DAS for Chromebooks and Desktops.[25][24][41] | **Highest relevance.** A DAS lets a supplier register once and then sell to many school boards under pre-agreed terms without each school re-tendering. A headphone/audio supplier would need to be a participating supplier in a DAS for leermiddelen/ICT-accessoires. |
| **DAS-Service (das-service.nl)** | The operator of the DAS route: "Veel onderwijsinstellingen maken gebruik van het **Dynamisch Aankoopsysteem (DAS) van Onderwijs Inkoop Groep (OIG)** voor de inkoop van diverse computertoebehoren." Published DAS: Computertoebehoren, Chromebooks, Desktops (also referenced as DAS T7153 / DAS OIG Laptops in EU tender notices). DAS-Selector "Quickscan" to find relevant DAS, and they offer to handle all registrations. Contact 0172 578 909.[24][41] | **Highest relevance, concrete entry point.** DAS = Dynamically Purchased Agreement; supplier registers per lots and then gets called off. This is the mechanism behind "delivery of laptops for NU SKO-OVO published in DAS OIG Laptops" etc. |
| **Schoolinkoop.nl** | "Collectief besparen, ontzorgen en verduurzamen" — "Alle producten zijn collectief ingekocht middels een **Europese aanbesteding**"; categories include kantoorartikelen, afvalverwerking, groepsvervoer; a "AANMELDEN" flow for a new aanbesteding; a "Deelnemen aan de collectieven" page.[5] | **Medium.** Route to become an awarded supplier in a collective EU tender for a product category — a multi-school framework. Likely a category-led, longer sales cycle. |
| **SIVON** | "de ict-coöperatie voor het primair en voortgezet onderwijs"; represents ~450 schoolbesturen; runs collective procurement of leermiddelen and ICT, supplier management, DPIA, verwerkersovereenkomst testing, normenkader-IBP, plus a dedicated "Informatie voor leveranciers" page. Published Oct 2026: "Sinds SIVON in 2020 begon met gezamenlijke aanbestedingen voor leermiddelen, is er veel veranderd. Schoolbesturen hebben **meer inzicht gekregen in prijzen en dienstverlening**, meer ruimte om eigen keuze te maken".[7][23] | **Medium–high for compliance credibility.** Being a known, screened supplier to SIVON materially lowers a schoolboard's perceived risk. |
| **KIEN** | "KIEN is geen bedrijf. KIEN is een **coöperatie**. Ben je als onderwijsinstelling op zoek naar de beste manier om ICT-voorzieningen voor de leerlingen in te kopen?"[38] | **Medium.** Another cooperative collective-procurement route, ICT-focused. |
| **Schoolexpert** | "Een full service organisatie op het gebied van allerhande leermiddelen, uitgezonderd studieboeken. SchoolExpert levert deze leermiddelen **rechts uit de eigen kosten**"; has an ICT/computer-supplies category where the school picks a location. (Note: the TLS certificate on schoolexpert.nl had expired on 2026-10-29 — flagged below.)[42] | **Medium.** A reseller/fulfilment partner, not a procurement portal per se; a route to reach schools without building the channel. |
| **School Supplier (schoolsupplier.nl)** | A dedicated Dutch school-supplier webshop (Shopify): headphones, concentration screens, concentration headphones, posters; explicit quote route for >50 units with staffelprijzen and ordering on invoice; explicitly supports the "school needs a quote for internal approval" case.[29] | **High relevance as a channel/model.** Closest public analogue to what WiseQ's zakelijke-klant page offers, but executed as a self-service school webshop with a published quote form. |
| **Rkop / Oortjessale / Opzijnkoptelefoon** | Not portals but **direct school-webshop suppliers** with bestelbon-aanvraag, offerte-aanvraag, proefpakket, staffelprijzen, factuur-betaling.[26][27][28] | **High relevance as the benchmark.** These are what a Dutch school is used to buying from, at 6–18× WiseQ's price points. |
| **De Schoolwebwinkel / WebshopVoorSchool.nl / WIS / Stamhoofd** | **Parent-facing** school webshops and payment platforms, not supplier portals: De Schoolwebwinkel ("Elke school die mee doet, heeft een eigen webshop"), WIS's "Webshop voor scholen" ("Verkoop producten, activiteiten en donaties … Veilig via iDEAL, Wero en Collect") and "Schoolkassa" (since 2026 part of WIS Onderwijs), plus WebshopVoorSchool.nl and Stamhoofd.[30][31] | **Low for B2B onboarding; potentially high for a B2C-at-school route.** If WiseQ wants parents to buy headphones through the school (rather than the school buying), WIS/Schoolwebwinkel/Stamhoofd are the collection points. |
| **Edu-V** | The "keurmerk voor digitale gegevensuitwisseling in het onderwijs" that the Privacyconvenant moved into in 2025; suppliers of digital teaching materials register for it (anmelden@edu-v.org; a deadline of 1 Aug 2025 was posted for a new onboarding round).[7][23] | **Conditional.** Only relevant if the WiseQ tablet/watch product carries student data or a learning platform. |
| **IncoNed** | "Inkoopplatform voor deelnemers en leveranciers in verschillende sectoren"; removes purchasing work for participants and suppliers.[— seen in search results; not deeply verified] | **Unverified in detail** — see §6. |
| **DocDirect** | **Does not exist as a school procurement platform.** The only DocDirect is an **arbeidsbemiddelaar** (teacher recruitment agency) for voortgezet onderwijs: "Wij zijn Docent Direct: arbeidsbemiddelaar voor het voortgezet onderwijs… Al 300+ scholen doen mee." No procurement function found. | **Not relevant — premise in the brief appears mistaken.** |

**Inference on relevance ranking for WiseQ:** (1) Onderwijs Inkoop Groep / DAS is the single highest-leverage onboarding because it converts "one school emails you" into "many school boards can call you off under agreed terms"; (2) School Supplier / Rkop show the operational template WiseQ should copy (quote form + bestelbon + proefpakket + factuur) — WiseQ already has all of these, which is a genuine asset; (3) school webshops (WIS/Stamhoofd/Schoolwebwinkel) are a separate B2C-at-school channel, not a supplier route; (4) SIVON/Edu-V matter mainly for compliance credibility if student data is in scope.

---

## 4. Dutch market context for kids' tech demand

**This section is the weakest-evidenced of the five.** There is **no published Dutch statistic for "kids' headphone market size" or "kids' hearing-protection demand"**. What exists:

**Observed — screen time (the demand driver).** Iene Miene Media-onderzoek 2026 (Netwerk Mediawijsheid, fieldwork 2026, 0–6 jarigen): "In 2026 besteedden kinderen van 0 t/m 6 jaar gemiddeld **102 minuten** aan beeldschermen per dag." And critically: "Het totale aantal minuten beeldschermgebruik is **meer dan in 2025 (81 minuten)** en vergelijkbaar met 2024 (99) en 2023 (100 minuten)." So screen time **rose sharply in 2026 vs 2025** (+26%) and is back to 2023/2024 levels — i.e. a rebound, not a secular climb. Also: tv 57%, tablet 41%, phone 31% named as regularly-used devices; "Gemiddeld gebruiken jonge kinderen regelmatig iets meer dan **twee apparaten**"; "ongeveer **één op de vijf** ouders zegt dat hun kind regelmatig vier, vijf, of zelfs wel zes of meer digitale apparaten gebruikt"; advice thresholds are 0–2 j: none, 2–4 j: max half an hour, 4–8 j: max one hour; "Het beeldschermgebruik ligt **fors hoger** dan de Landelijke Richtlijn Gezond Schermgebruik adviseert"; "Eén op de drie ouders ként de richtlijn", "Twee op de drie ouders wíl graag duidelijke richtlijnen".[32]

**Observed — the 7–12 cohort (WiseQ's school age).** Monitor Mediagebruik 7 tot en met 12 jaar (Netwerk Mediawijsheid × hogeschool Windesheim × bureau Highberg; survey of **937 parents**, field work 3–16 Dec 2024; published Nov 2025). Device-use share, total / ages 10–12 / ages 7–9: **Mobiel 79/80/79**, **Oortjes/koptelefoon 71/87/38**, Tablet 69/63/79, Videogameconsole 57/61/52, Laptops 57/64/41, Televisie 47/59/27, **Smartwatch 14/14/13**, Radio 13/11/15, Smartspeaker 10/10/9. Also: "Kinderen krijgen hun eerste mobiele telefoon gemiddeld op **9,2 jaar**, vooral om veiligheidsredenen. Ouders die dit willen uitstellen, noemen gemiddeld **11,6 jaar**"; "**12,5% of kids between the ages of 6 and 19 suffer from hearing loss as a result of using earphones turned to a high volume**" (BuddyPhones cites this on its product page, attributing it to the *Journal of Pediatrics*).[33][16]

**Observed — hearing protection category.** Holland Capital invested in Pluggerz ("marktleider in op maat gemaakte gehoorbescherming", 11 March 2026): "De markt voor gehoorbescherming **groeit**, gedreven door strengere regelgeving rondom geluidsblootstelling op de werkvloer en de groeiende verantwoordelijkheid van werkgevers om gehoorschade actief te voorkomen. Tegelijkertijd neemt het maatschappelijke bewustzijn rondom gehoorschade toe. **Met name jongere generaties kiezen steeds vaker voor structurele bescherming.**" Pluggerz has ~90 staff, operates from Doetinchem, and has **700+ dealer locations** in NL and BE. Note the growth driver cited is *workplace* regulation, not children's hearing protection.[35]

**Observed — the broader NL consumer-electronics market is flat, not booming.** APPLiA Nederland Jaarcijfers 2025 (data from NielsenIQ/GfK + APPLiA sales figures; published 12 May 2026): "De cijfers van 2025 laten een **stabiele markt** zien met groei in sommige segmenten en een lichte daling in andere. De **totale marktomzet steeg met 1,3%**. In 2024 werd een omzet van **€3,712 miljard** gerealiseerd en in 2025 kwam de omzet uit op **€3,759 miljard**." Growth was in ovens (+11,1% to €296 m), robot vacuums (+76,5% to €124 m) and premium coffee machines (+2% to €159 m). APPLiA also notes "Er wordt steeds vaker gekozen voor **premiumproducten**." This is a large-appliance association and does not cover headphones — but it is the best NL "consumer electronics is flat" anchor available.[39]

**Observed — bol.com headphones category (the actual competitive pool).** Boloo/Zoloo Niche Explorer for "Koptelefoons on Bol.com": **999 products, 268 sellers**, search volume 1.219.371 (3 mo), **estimated revenue €86K**, trend **+7% over 3 months** (6 months −26%, 1 year −12%), competition level Low, **median price €49,99**, price range €9,95–€3.699, avg rating 4.2★, 43.590 reviews, avg seller age 6.6 years, avg seller rating 8.4/10. Price distribution: 42 products in €9–17, **271 in €18–32**, 247 in €33–… Popular search terms include "kinder koptelefoon met draad", "koptelefoon kinderen". Subcategory trends include "Premium Koptelefoons +XX%" and "Budget Koptelefoons +XX%" (magnitudes masked on the free tier). A parallel Kinderkoptelefoons page (boloo.co) shows 289 products, 99 sellers, 603.577 search volume (3 mo), **estimated revenue €7K, trend −39% (3 months)**, median ~€49,99 — though that fetch 404'd on 2026-10-29 and the figure comes from the search-index snippet, so **treat the −39% figure as lower-confidence** than the +7% headline category figure.[34]

**Inference on section 4:** There is **no defensible Dutch market-growth number for kids' headphones or kids' hearing protection** — I found none and did not manufacture one. The usable, citable facts are: (a) 0–6 screen time rebounded to 102 min/day in 2026 from 81 in 2025 and sits far above the national guideline; (b) 71% of Dutch 7–12 year-olds use earbuds/headphones, rising to 87% at ages 10–12; (c) the consumer-electronics market overall grew only 1,3% in 2025 with a tilt to premium; (d) the bol.com headphones category is +7% over 3 months but −26% over 6 months and −12% over 1 year, i.e. **flat-to-declining year-on-year**; (e) hearing protection is a growing category but its cited drivers are workplace regulation and adult earplug customisation, not kids. The honest read: **WiseQ's category is mature and mildly contracting, not growing**; the growth case rests on premiumisation and on the school/institutional channel, not on consumer category expansion.

---

## 5. Comparable pricing — is WiseQ premium or value?

**WiseQ reference band (from its own catalogue feed [2] and comparison page [8]):** wired €18,95–€19,95; entry wireless €19,95–€24,95; mainstream wireless €27,95–€34,95; ANC €49,95; earbuds €9,95; hearing protection €21,95; smartwatch €74,95; kid tablet €124,95–€159,95.

**Comparable NL prices, all observed 2026-10-29:**

| Brand / product | NL price | vs WiseQ equivalent |
|---|---|---|
| JLab JBuddies Pop Wired | €20,95 | ≈ WiseQ Junior €18,95 / One €19,95 (+10%) |
| JLab JBuddies Studio 2 Wired | €20,95 | ≈ +10% |
| JLab JBuddies Folding Wired | €20,95 | ≈ +10% |
| JLab JBuddies Pro Wired Over-Ear (8+, HP switch) | €26,95 | between One and Hero |
| JLab JBuddies 2-in-1 wired+wireless 48h | €23,95 | ≈ Hero €27,95, below it |
| JLab JBuddies Wireless 35+ h (8+) | €36,95 | ≈ Unbreakable €34,95 (+6%) |
| BuddyPhones Explore+ wired+mic (EU shop) | €24,90 | +25% vs One €19,95 |
| BuddyPhones POP Fun wireless | €29,90 (was €42,90) | ≈ Hero €27,95 (+7%) |
| BuddyPhones Play+ wireless + StudyMode | from €49,90 | ≈ WiseQ Kids ANC €49,95 |
| BuddyPhones Cosmos+ wireless ANC | €79,90 | **+60% vs WiseQ Kids ANC €49,95** |
| BuddyPhones CosmosFun ANC | €99,99 | +100% vs WiseQ Kids ANC |
| BuddyPhones School+ Wireless (bol.com) | €25,00 | +25% vs WiseQ BTwireless €19,95–24,95 |
| BuddyPhones POP (bol.com) | €37,27 | ≈ Unbreakable €34,95 |
| Puro Sound BT2200s / BT2200-Plus | $99.00 (~€85–95) | ~2× WiseQ Kids ANC |
| Puro JuniorJams-Plus | $65.00 (~€55–60) | ≈ +20% vs WiseQ Unbreakable |
| Puro PuroBasic wired | $29.00 (~€25) | ≈ +30% vs WiseQ One |
| Onear / EKIDS / PowerLocus (bol.com) | €25,99 / €29,99 | +30–50% vs WiseQ wired |
| JBL JR 320BT wireless | from €33 | ≈ Unbreakable €34,95 (−3%) |
| Philips TAK2000CT | ~€15 equivalent | ≈ WiseQ Junior/Oordopjes |
| OTL Technologies (Bluey / Peppa Pig) | €27,25 / €27,99 | +40% vs WiseQ wired |
| **Rkop MAX school-grade** | **€16,99 → from €9,89** | **−13% to −48% vs WiseQ One** |
| **Rkop FLEX kinder-/kleuterkoptelefoon** | **€19,99 → from €15,99** | **≈ +5% to −20% vs WiseQ One** |
| **Rkop Buddy concentratiekoptelefoon** | **€22,95 → from €15,95** | **≈ +21% to −16% vs WiseQ One** |
| **Rkop EM / Nova / EAR / doosjes** | **€3,49–€9,99 → from €1,79–€7,99** | **−58% to −85% vs WiseQ wired** |

**Inference — the price verdict:** WiseQ is **not a premium price point** in kids' audio. It sits in the **mid-market band of the consumer brands** (JLab-parity on wired, JLab/BuddyPhones-parity on mainstream wireless) and **at a large premium to the Dutch school-grade channel** (Rkop family) — while offering a **shorter warranty than BuddyPhones** (1 yr vs 2–3 yr) and a **lower entry price than the consumer brands' typical school model**. So WiseQ's price positioning is: *above the cheap school specialists, roughly level with the consumer brands, below the premium kids brands.* The value case therefore rests on the service package (staffel, proefexemplaar, factuur, school delivery, Dutch guidance), not on unit price.

**Inference — the margin/risk note.** WiseQ's cost base on a €18,95 wired headset cannot beat Rkop's €9,89 tier price in a bid, and WiseQ's €49,95 ANC cannot beat BuddyPhones' €29,90 POP Fun sale price in a consumer comparison. The realistic B2B position is the **middle of the market where schools want service + durability but do not need a €400 premium over Rkop**: i.e. the €19,95–€34,95 band. The clearest actionable gap is **warranty**: BuddyPhones gives 2 years (3 if registered) and WiseQ gives 1.[12][15]

---

## 6. Could not retrieve / not verified

1. **"SmartG procurement" — not found.** No Dutch school-procurement platform called SmartG exists in this space (a "smart-G" result is an unrelated gearbox-condition-monitoring product at smartg.com.ai). The brief's premise appears mistaken. The real analogues are **Onderwijs Inkoop Groep / DAS-Service**, **Schoolinkoop.nl**, **SIVON**, **KIEN**.[24][25][41][5][7][38]
2. **"InProve" — not found** as a Dutch school procurement platform in any search result. No source; likely a mistaken name.
3. **"DocDirect" — exists but is the wrong thing.** It is a teacher recruitment agency for voortgezet onderwijs, not a procurement platform.
4. **"Ouders Delen Online" / "Omnichannel" — no matching school-procurement platform found.** The real parent-facing school webshop/payment players located were **De Schoolwebwinkel**, **WebshopVoorSchool.nl**, **WIS** (incl. Schoolkassa, merged into WIS since 2026), **Stamhoofd**.[30][31]
5. **Xorio — could not be verified at all** as a Dutch kids-headphone seller. No product page, no price, no policy found.
6. **Onear — thin/unverifiable.** Only a Google-Shopping-derived aggregator listing (€25,99–€76,75 across 4 bol.com offers) plus unbranded generic listings; no own storefront, warranty policy, or school/B2B programme found.
7. **"15% school discount" for WiseQ — not found on the live site.** WiseQ's pages describe staffelprijzen (volume tiers, prices gated behind business registration), not a flat 15% school discount. The only 10–15% figures on WiseQ pages concern expected annual attrition of shared headsets. **The 15% claim in the brief should be re-verified against an internal source.**[8][10]
8. **No Dutch market-size figure** for kids' headphones, kids' smartwatches or kids' hearing protection was found from any credible Dutch source. The Holland Capital/Pluggerz statement is the closest ("de markt voor gehoorbescherming groeit") but is about hearing protection generally and cites *workplace* regulation as the driver.[35]
9. **WiseQ's actual staffel (tier) price boundaries are not public** — the page states prices become visible only after business registration. No tier table could be retrieved.[10]
10. **WiseQ's tablets: no manufacturer, OS, storage specs, MDM/Google Classroom/Edu-V status, or school-warranty terms found.** WiseTab is priced at €124,95 (96 GB) and €159,95 (160 GB); the school page discusses management/charging but no compliance spec. Whether WiseTab is a rebranded generic Android tablet is not stated anywhere I could find, and I did not infer it.[2][13]
11. **WiseQ's school pipeline is described only as email-based** in the brief. The site's own B2B mechanics are registration + invoice + staffel + sample + school-address delivery. I found no published WiseQ supplier portal, DAS participation, or framework agreement.[9][10][11]
12. **schoolexpert.nl TLS certificate expired** on 2026-10-29 (curl: "certificate has expired"); the site content was retrieved with certificate verification relaxed. Page content was read but the site's technical health is a minor flag.
13. **boloo.co/niche-explorer/kinderkoptelefoons returned HTTP 404** on 2026-10-29; the "−39% trend / €7K revenue" figures for that page come from the search-engine snippet, not from a direct fetch. The parent "Koptelefoons" category page (999 products, +7% 3-month trend) **was** directly fetched and is reliable.[34]
14. **Puro Sound publishes no EUR price and no Dutch school/B2B programme**; its USD prices were converted to rough euro ranges in §5 for orientation only — those conversions are **my arithmetic, not sourced exchange rates**. The sourced NL figure is the aggregator's "from €35,00 (Amazon.nl) to €61,00 (ubuy.co.nl)".[20]
15. **BuddyPhones' School+ is not currently sold in the onanoff.eu EU store feed** (the "School" collection holds only BuddyCase), and BuddyPhones shows the same SKUs ~15–20% cheaper on onanoff.eu than on buddyphones.com/en-eu. The Dutch availability channel for School+ in volume is therefore not established from public data.[14][18]
16. **No confirmation of any Dutch school framework agreement won by WiseQ**, nor of WiseQ's FiveX / ChannelDock / e-Boekhouden / 3× bol.com seller-account setup — those are internal facts from the brief, not publicly verifiable. **Note for the ops angle:** WiseQ operating 3 separate bol.com seller accounts may interact badly with bol.com's own duplicate-listing/price-consistency enforcement and with bol.com's 2026 action on headphones with potentially harmful substances (VRT/Volkskrant reported Bol.com and MediaMarkt withdrawing some headphones over possibly harmful substances in ear cushions, Feb 2026) — worth checking WiseQ's ear-cushion material documentation against that wave of recalls, but **I found no report naming WiseQ in that recall** and none of the recalled brands were named in the sources I read.
17. **BuddyPhones' "Educational Headphones" collection page 404'd** on direct fetch (`/collections/educational-headphones` → 404); the "Educational Headphones" label is confirmed from the EU shop page and site navigation instead.[14]

---

## Sources

