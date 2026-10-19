"""Disclaimer text stamped into every published output.

The full disclaimer lives in README.md#disclaimer; keep these short forms in sync with it.
"""

# Plain text: written into each pack's provenance.json.
SHORT = ('NOT FOR NAVIGATION. FOR EDUCATIONAL USE ONLY. Although this data is extracted '
         'directly from official FAA sources, it is provided "as is" with no representation '
         'or warranty that it is accurate, complete, or current. Use it at your own risk.')


def short_markdown(readme_url):
    """Markdown form for chart READMEs and release notes, linking the full disclaimer."""
    return ('**Not for navigation. For educational use only.** Although this data is extracted '
            'directly from official FAA sources, it is provided "as is" with no representation '
            'or warranty that it is accurate, complete, or current. Use it at your own risk; '
            f'see the [full disclaimer]({readme_url}).')
