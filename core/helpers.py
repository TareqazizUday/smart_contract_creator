"""
Helper functions and utilities
"""
import markdown as md
from markdown.extensions import fenced_code, tables, nl2br


def markdown_to_html(text):
    """Convert markdown text to HTML with proper formatting"""
    if not text:
        return ""
    
    # Use markdown extensions for better HTML output
    extensions = [
        'fenced_code',
        'tables',
        'nl2br',  # Convert newlines to <br>
        'extra'   # Enable extra features
    ]
    
    try:
        html = md.markdown(
            text,
            extensions=extensions,
            output_format='html5'
        )
        
        # CRITICAL FIX: Python markdown escapes HTML tags by default for security
        # We need to unescape our intentional anchor tags for legal citations
        # so they remain clickable in PDFs
        import re
        import html as html_module
        
        # Strategy 1: Unescape ALL anchor tag patterns comprehensively
        # Handle all variations of escaped anchor tags (with more patterns)
        
        # Pattern 1: Standard escaped anchor with target="_blank" and brackets
        # [&lt;a href=&quot;URL&quot; target=&quot;_blank&quot;&gt;Text&lt;/a&gt;]
        html = re.sub(
            r'\[&lt;a\s+href=&quot;([^&"]+)&quot;\s+target=&quot;_blank&quot;&gt;([^&<]+)&lt;/a&gt;\]',
            r'[<a href="\1" target="_blank">\2</a>]',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Pattern 2: Escaped anchor without brackets
        # &lt;a href=&quot;URL&quot; target=&quot;_blank&quot;&gt;Text&lt;/a&gt;
        html = re.sub(
            r'&lt;a\s+href=&quot;([^&"]+)&quot;\s+target=&quot;_blank&quot;&gt;([^&<]+)&lt;/a&gt;',
            r'<a href="\1" target="_blank">\2</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Pattern 3: Handle simple escaped anchor tags (no target)
        # &lt;a href="URL"&gt;Text&lt;/a&gt;
        html = re.sub(
            r'&lt;a\s+href="([^"]+)"[^&]*&gt;([^&<]+)&lt;/a&gt;',
            r'<a href="\1">\2</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Pattern 4: Handle case where quotes might also be escaped with single quotes
        # &lt;a href='URL' target='_blank'&gt;Text&lt;/a&gt;
        html = re.sub(
            r"&lt;a\s+href='([^']+)'\s+target='_blank'&gt;([^&<]+)&lt;/a&gt;",
            r'<a href="\1" target="_blank">\2</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Pattern 5: Handle escaped anchor with &amp;quot; (double escaped)
        html = re.sub(
            r'&lt;a\s+href=&amp;quot;([^&]+)&amp;quot;[^&]*&gt;([^&<]+)&lt;/a&gt;',
            r'<a href="\1">\2</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        
        # Strategy 2: Direct character replacement for remaining escaped HTML entities
        # This ensures any remaining escaped characters are properly unescaped
        replacements = [
            ('&lt;a ', '<a '),
            ('&lt;/a&gt;', '</a>'),
            ('href=&quot;', 'href="'),
            ('&quot; target=&quot;', '" target="'),
            ('&quot;&gt;', '">'),
            ('target=&quot;_blank&quot;', 'target="_blank"'),
            ('&amp;quot;', '"'),  # Handle double-escaped quotes
            ('&amp;lt;', '<'),    # Handle double-escaped <
            ('&amp;gt;', '>'),    # Handle double-escaped >
        ]
        
        for old, new in replacements:
            html = html.replace(old, new)
        
        # Strategy 3: Final pass with html.unescape for any remaining entities
        # But only for content that looks like links
        if '&' in html and ('href' in html.lower() or 'http' in html.lower()):
            try:
                html = html_module.unescape(html)
            except:
                pass  # If unescape fails, continue with current HTML
        
        # Post-process HTML to ensure proper spacing and formatting
        # Add spacing after headers
        html = re.sub(r'(</h[1-6]>)', r'\1\n', html)
        # Ensure lists have proper spacing before and after
        html = re.sub(r'(</ul>|</ol>)', r'\1\n', html)
        html = re.sub(r'(<ul>|<ol>)', r'\n\1', html)
        # Ensure proper spacing around paragraphs
        html = re.sub(r'(</p>)', r'\1\n', html)
        html = re.sub(r'(<p>)', r'\n\1', html)
        
        return html
    except Exception as e:
        # Fallback to basic markdown if extensions fail
        try:
            return md.markdown(text, extensions=['extra'])
        except:
            return md.markdown(text)


def clean_output(text):
    """Remove explanatory phrases and clean up the output"""
    explanatory_phrases = [
        "I have extracted", 
        "The text in the image", 
        "As accurately as possible",
        "The image contains", 
        "I've transcribed", 
        "I've extracted",
        "The quality of the image",
        "The text appears to be",
        "From the image provided",
        "The content of the image",
        "Due to image quality",
        "Here is the text",
        "Text extraction complete",
        "Here's the extracted text",
        "The text from the image is",
        "I've maintained",
        "Here is the corrected text",
        "Here's the corrected text",
        "The corrected text is",
        "Corrected text:",
        "Here is the improved text",
        "Here's the improved text",
        "The improved text is",
        "Improved text:",
        "Based on the image",
        "After analyzing the image",
        "Upon reviewing the image",
        "Looking at the image",
        "From what I can see",
        "I can see that",
        "The document appears to",
        "This appears to be",
        "The text reads",
        "The document reads",
        "According to the image",
        "As shown in the image",
        "The image shows",
        "I notice that",
        "It appears that",
        "The content appears to be",
        "This looks like",
        "The document contains",
        "I can read",
        "The visible text is",
        "The readable text is"
    ]
 
    # Split text into lines
    lines = text.split('\n')
    cleaned_lines = []
    
    # Process each line
    for line in lines:
        line = line.strip()
        if not line:  # Skip empty lines
            continue
            
        should_keep = True
        for phrase in explanatory_phrases:
            if phrase.lower() in line.lower():
                should_keep = False
                break
        
        if should_keep:
            cleaned_lines.append(line)
    
    # Join lines and remove extra whitespace
    result = '\n'.join(cleaned_lines).strip()
    
    # Remove any remaining artifacts
    result = result.replace('**', '').replace('*', '')
    
    return result
