● Two areas to optimize in each step:

  ---
  Step 3 — Content Classifier

  Problem 1: Too many Groq API calls
  From your output, 6 out of 10 articles fell through to Groq because keywords didn't match. That means 60% of articles
  are hitting the API unnecessarily. The keyword lists need expanding.

  For example "How can Slot stop the boos" — "Liverpool fans" should trigger club_update but no keyword caught it.
  Adding words like "manager", "fans", "squad", "pressure", "future", "sacked", "fired", "coach" to the club_update
  signals would catch most of these without any API call.

  Problem 2: Non-football articles passing through
  The Sinner/Djokovic tennis article got classified as breaking_news. We should add a football relevance check before
  classification — if the headline contains no football-related word at all, skip it entirely before even classifying.

  Problem 3: Classify in batches
  Instead of one Groq call per article, send 10 headlines in one prompt and get 10 classifications back. This is 10x
  cheaper on API quota and much faster.

  ---
  Step 4 — Script Generator

  Problem 1: No validation on output
  Groq sometimes returns a script that is too short, too long, or starts with "Here is your script:" instead of the
  actual script. We need to add a simple check — if word count is below 50 for a main script, regenerate once.

  Problem 2: Short scripts are wasteful
  The short script (15 seconds) is being generated with a separate Groq call. We could generate both main and short in
  one single API call by combining the prompts, cutting the number of API calls per news item in half.

  Problem 3: No caching
  If two RSS feeds both pick up the same transfer story, we generate two separate scripts for the same news. Adding a
  simple check — if a script already exists in the database for a similar headline — skip generation entirely.

  ---
  Priority order to implement:
  1. Expand keyword lists (biggest impact, free, 5 minute fix)
  2. Add football relevance check (stops wasted processing)
  3. Combine main + short into one Groq call (halves API usage)
  4. Add script output validation (improves quality)
  5. Batch classification (more complex, lower priority)

  Want me to implement these one by one starting with the keyword expansion?