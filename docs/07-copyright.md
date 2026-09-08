# Sources, copyright and sharing results

This project’s default example now fetches **Wikipedia community text**, with
source credit. It also supports your original writing, permission-cleared
material and appropriately verified public-domain works. This is a practical
reuse policy, not a legal certification of every input or model reply.

## Wikipedia: a useful source with conditions

Wikipedia community text is generally reusable under **CC BY-SA 4.0**.
Wikimedia permits attribution through links to the articles, whose histories
identify contributors. Keep any additional attribution notices attached to
imported material. [Wikimedia Terms of Use, section 7](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content).

The page and Wikipedia fetcher record article links, contributor/history
links, the licence, retrieval time and any revision ID reported by the API.
That revision is observed metadata, not a guarantee that a separately cached
extract is an exact snapshot of that revision. Prompts also identify the
changes: plain-text extraction, excerpting and, when used, masking names.
Attribution is kept with the copies people keep and share (downloaded
prompts, `SOURCES.md`, reports, JSON), not inside the prompt sent to the
model: naming the work would tell the model which book to recall and could
leak a masked name, which would corrupt the test. Sending text to an API is
use, not redistribution.

Under CC BY-SA, credit and a licence link must accompany reuse, changes must
be identified, and shared adaptations must use the same or an allowed
compatible licence. Do not impose additional restrictions on licensed
material. Our notices offer the Wikipedia excerpt/adaptation material under
CC BY-SA 4.0; they do not relicense unrelated software or third-party content.
[Creative Commons licence summary and legal-code link](https://creativecommons.org/licenses/by-sa/4.0/).

**Wikipedia is not a blanket permission slip.** Third-party quotations,
images and other media can have separate rights or rely on an exception
specific to Wikipedia’s use. This tool fetches text only; inspect the source
and any special notices before using its excerpts. A model reply may also
contain unrelated protected material, so review it before publishing.
[Wikipedia’s reuse guidance](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content).

## What to use for your own tests

| Source | What to establish before sending or reproducing it |
|---|---|
| Your writing | You own the relevant rights and may share it; employer, coauthor or confidentiality obligations can still matter |
| Permission-cleared text | Permission covers the intended provider upload, reproduction, adaptation and any redistribution |
| Openly licensed text | The actual licence permits your use; preserve required credits/notices and follow adaptation and sharing conditions |
| Public-domain text | The relevant work, translation and edition are public domain under the law applicable to your use |
| A purchased book, paywalled article or arbitrary web page | Access alone is not a reuse licence; obtain suitable permission or have a separately assessed legal basis |

The browser asks for a rights basis when you paste, upload or edit text.
For open-licensed or public-domain inputs it also requires source/rights
notes. This is your declaration, not an automated verification. Do not use a
licence with incompatible restrictions just because it is labelled “open”.
A short excerpt, name-cloze prompt or “research” label is not an automatic
copyright exception. Check the selected provider’s terms as well.

## The optional Austen example

The embedded example is original English prose from Jane Austen’s
*Pride and Prejudice* (1813), sourced from [ebook 1342](https://www.gutenberg.org/ebooks/1342).
Illustrations and edition captions have been removed; no modern translation
is included. We credit Austen and link the source. The CLI’s Gutenberg set
is an explicit list of nineteenth-century novels, not arbitrary ebooks.

Project Gutenberg’s copyright determinations concern the United States;
its catalogue is not a worldwide public-domain guarantee. Check local law
and the particular edition when reusing its material.
[Project Gutenberg permission guidance](https://www.gutenberg.org/policy/permission.html).

## Keeping attribution intact

- **Browser:** source notices appear below loaded text, as a credits block
  at the end of "copy all" and downloaded prompt files (kept out of the
  individual prompts you paste), in report details and in JSON downloads. Editing fetched
  text retains upstream credit and marks the edit; added material needs its
  own rights basis. Preserve the notices when you share.
- **CLI:** fetched Wikipedia files have `<file>.sources.json` sidecars. Keep
  them with the text. Old Wikipedia cache files without these sidecars are
  left on disk but are not reused automatically; fetch again for attributed
  data. Text/manual exports carry the notices, and run reports with sources
  include `SOURCES.md`. Min-K% summaries also retain source metadata.
- **Other CLI files:** supply a sidecar using the same format if attribution
  is required. The CLI and legacy local web UI do not independently verify
  permissions or licences; users remain responsible for source selection and
  for required notices in material pasted into the legacy UI.

Example sidecar for your own licensed source:

```json
{
  "sources": [{
    "title": "Title of the source",
    "author": "Author or required attribution party",
    "url": "https://example.org/original",
    "license": "Actual licence name",
    "license_url": "https://example.org/licence",
    "changes": "Describe excerpting, masking, edits or paraphrasing",
    "notice": "Preserve any additional source notices here"
  }]
}
```

The tool does not publicly post model replies automatically. A downloaded
report is not permission to distribute everything it contains. In particular,
source attribution does not grant rights in unrelated text a model produces.

## Reuse permission and experimental quality are separate

Wikipedia is convenient for licensed encyclopaedia prose. It is not
necessarily the best control for a novel, and a newly created article may
reuse older wording. Match genre and predictability, and do not label recent
Wikipedia text “certainly unseen”. Attribution may cue a model to the source;
keep it consistent across comparisons. A cloze probe is omitted when the
attribution itself reveals the missing name.

Research papers are linked and discussed; the site does not redistribute
their copyrighted book datasets or implement their restriction-bypassing
extraction workflows. For an uncertain commercial deployment or contested
source, get jurisdiction-specific legal advice rather than relying on a
checkbox or this guide.
