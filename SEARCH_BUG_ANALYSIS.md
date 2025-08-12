# IIIF Search Bug Analysis: KCDC_A-005 Not Found

## Problem Description

The madoc-search-service fails to find IIIF manifests with IDs like `KCDC_A-005`, while successfully finding `KCDC_B-005` and `KCDC_C-005`. The issue occurs despite `KCDC_A-005` existing in the database.

## Root Cause

PostgreSQL's full-text search with the English dictionary treats single letter "A" as a stop word, filtering it out during tokenization. When hyphenated words are parsed, they create multiple tokens:

**KCDC_A-005 tokenization:**
- `kcdc_a-005` (full word)
- `kcdc` (part)
- ~~`a` (filtered as stop word)~~
- `005` (part)

**KCDC_B-005 tokenization:**
- `kcdc_b-005` (full word)  
- `kcdc` (part)
- `b` (preserved)
- `005` (part)

## Solutions (Recommended Order)

### Solution 1: Create Custom Text Search Configuration (RECOMMENDED)

Create a custom text search configuration that doesn't filter hyphenated word parts:

```sql
-- Create custom configuration based on English
CREATE TEXT SEARCH CONFIGURATION madoc_search (COPY = english);

-- Remove hyphenated word part filtering to prevent "A" from being lost
ALTER TEXT SEARCH CONFIGURATION madoc_search 
DROP MAPPING FOR hword_asciipart, hword_part;

-- Update your search queries to use this configuration
```

### Solution 2: Use Alternative Search Strategy

Modify the search logic to handle exact ID matches differently:

```python
# In parsers.py, modify the search string processing
if search_string and looks_like_id(search_string):
    # For ID-like strings, use icontains instead of full-text search
    postfilter_q.append(
        Q(indexables__indexable__icontains=search_string)
    )
else:
    # Use existing full-text search logic
    if language:
        filter_kwargs["indexables__search_vector"] = SearchQuery(
            search_string, config=language, search_type=search_type
        )
    else:
        filter_kwargs["indexables__search_vector"] = SearchQuery(
            search_string, search_type=search_type
        )
```

### Solution 3: Preprocess Search Queries

Add preprocessing to handle hyphenated identifiers:

```python
def preprocess_search_string(search_string):
    """Preprocess search strings to handle hyphenated IDs better"""
    # Check if this looks like a hyphenated ID
    if re.match(r'^[A-Z]+_[A-Z]-\d+$', search_string):
        # For hyphenated IDs, also search for the full string as a phrase
        return f'"{search_string}"'
    return search_string
```

### Solution 4: Use Different Search Type

Modify the search to use 'phrase' or 'websearch' type for better exact matching:

```python
# In parsers.py, line 256-265
if search_string:
    # For exact-looking strings, use phrase search
    if re.match(r'^[A-Z]+_[A-Z]-\d+$', search_string):
        search_type = 'phrase'
    
    if (non_latin_fulltext or is_latin(search_string)) and not search_multiple_fields:
        if language:
            filter_kwargs["indexables__search_vector"] = SearchQuery(
                search_string, config=language, search_type=search_type
            )
        else:
            filter_kwargs["indexables__search_vector"] = SearchQuery(
                search_string, search_type=search_type
            )
```

## Implementation Details

The recommended solution (Solution 1) requires:
1. Database migration to create the custom configuration
2. Update of existing GIN indexes to use the new configuration  
3. Modification of settings to use the new configuration as default

## Testing

After implementing any solution, test with:
- `KCDC_A-005` (should now return 1 result)
- `KCDC_B-005` (should continue to work)
- `KCDC_C-005` (should continue to work)
- Regular text searches (should continue to work normally)