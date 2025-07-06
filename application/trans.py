import os
from datetime import datetime

def trans_md_to_html(md_content, question):
    # Read styles.css content
    with open('application/styles.css', 'r', encoding='utf-8') as f:
        css_content = f.read()

    lines = md_content.split('\n')
    
    # Get main title from first # heading
    title = question
    for line in lines:
        if line.startswith('# '):
            title = line[2:]
            break

    # Get all subtitles from ## headings
    subtitles = []
    for line in lines:
        if line.startswith('## '):
            subtitles.append(line[3:])

    # Create HTML template
    html_template = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
{css_content}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>{title}</h1>
            <p class="subtitle">{datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')} 기준</p>
        </div>
    </header>

    <main class="container">
"""
    # Dynamically generate sections for each subtitle
    for i, subtitle in enumerate(subtitles):
        html_template += f"""
        <section class="content-section-{i}">
            <h2>{subtitle}</h2>
            {convert_section_content(md_content, subtitle)}
        </section>
"""

    html_template += """
    </main>

    <footer>
        <div class="container">
            <p>&copy; """ + str(datetime.now().year) + f""" {title}</p>
            <p>최종 업데이트: """ + datetime.now().strftime('%Y년 %m월 %d일') + """</p>
        </div>
    </footer>
</body>
</html>"""

# template of intro, conclusion
        # <section class="intro">
        #     <p>부여 지역 4인 가족 숙박에 대해 조사한 결과를 알려드리겠습니다.</p>
        # </section>
        # <section class="conclusion">
        #     <p>구체적인 숙소 정보나 추가 문의사항이 있으시다면 말씀해 주세요.</p>
        # </section>

    return html_template

def convert_markdown_table(content):
    """Convert markdown table to HTML table format"""
    html = ""
    lines = content.split('\n')
    in_table = False
    headers = []
    
    for line in lines:
        # Skip separator line (| --- | --- |)
        if line.strip().startswith('|') and '---' in line:
            continue
            
        if line.strip().startswith('|'):
            if not in_table:
                html += '<div class="table-responsive">\n<table>\n'
                in_table = True
                
            # Split line by | and remove empty elements
            cells = [cell.strip() for cell in line.split('|') if cell.strip()]
            
            if not headers:  # First line is header
                headers = cells
                html += '<thead>\n<tr>\n'
                for cell in cells:
                    html += f'<th>{cell}</th>\n'
                html += '</tr>\n</thead>\n<tbody>\n'
            else:  # Data rows
                html += '<tr>\n'
                for i, cell in enumerate(cells):
                    # Check if cell contains a link
                    if '[' in cell and '](' in cell:
                        text = cell[cell.find('[')+1:cell.find(']')]
                        url = cell[cell.find('(')+1:cell.find(')')]
                        html += f'<td><a href="{url}" target="_blank" class="booking-btn">{text}</a></td>\n'
                    else:
                        html += f'<td>{cell}</td>\n'
                html += '</tr>\n'
        elif in_table:
            html += '</tbody>\n</table>\n</div>\n'
            in_table = False
    
    # Close table if still open
    if in_table:
        html += '</tbody>\n</table>\n</div>\n'
    
    return html

def convert_section_content(content, section_title):
    """Convert section content to HTML format"""
    html = ""
    lines = content.split('\n')
    in_section = False
    section_content = []
    current_subsection = None
    subsection_content = []
    
    def process_bold_text(text):
        """Convert **text** to <strong>text</strong>"""
        processed_text = text
        while '**' in processed_text:
            start = processed_text.find('**')
            end = processed_text.find('**', start + 2)
            if end != -1:
                bold_text = processed_text[start+2:end]
                processed_text = processed_text[:start] + f'<strong>{bold_text}</strong>' + processed_text[end+2:]
            else:
                break
        return processed_text

    def process_image(text):
        """Convert ![alt](url) to <img> tag"""
        if '![' in text and '](' in text:
            alt_start = text.find('![') + 2
            alt_end = text.find(']', alt_start)
            url_start = text.find('(', alt_end) + 1
            url_end = text.find(')', url_start)
            
            if alt_end != -1 and url_end != -1:
                alt_text = text[alt_start:alt_end]
                url = text[url_start:url_end]
                return f'<img src="{url}" alt="{alt_text}" class="markdown-image">'
        return text
    
    # Collect all content in the section
    for line in lines:
        if line.startswith(f'## {section_title}'):
            in_section = True
            continue
        elif line.startswith('## ') and in_section:
            break
        elif in_section:
            section_content.append(line)  # Add all content to section_content
            if line.startswith('### '):
                # Process previous subsection if exists
                if current_subsection and subsection_content:
                    html += process_subsection(current_subsection, subsection_content)
                current_subsection = line
                subsection_content = []
            else:
                subsection_content.append(line)
    
    # Process the last subsection
    if current_subsection and subsection_content:
        html += process_subsection(current_subsection, subsection_content)
    
    # Check if section contains a table and no ### sections
    has_table = any(line.strip().startswith('|') for line in section_content)
    has_h3 = any(line.startswith('### ') for line in section_content)
    
    if has_table and not has_h3:
        table_content = []
        in_table = False
        for line in section_content:
            if line.strip().startswith('|'):
                in_table = True
                table_content.append(line)
            elif in_table and not line.strip().startswith('|'):
                in_table = False
                html += convert_markdown_table('\n'.join(table_content))
                table_content = []
                if line.strip():
                    processed_line = process_bold_text(line.strip())
                    processed_line = process_image(processed_line)
                    html += f'<p>{processed_line}</p>\n'
            elif not in_table and line.strip():
                processed_line = process_bold_text(line.strip())
                processed_line = process_image(processed_line)
                html += f'<p>{processed_line}</p>\n'
        
        # Process any remaining table content
        if table_content:
            html += convert_markdown_table('\n'.join(table_content))
    elif not has_h3:
        html += f'<div class="subtitle-details">\n'
        html += f'<div class="body">\n'
        
        current_list_type = None
        for line in section_content:
            if line.strip():
                if line.startswith('- '):
                    if current_list_type != 'ul':
                        if current_list_type == 'ol':
                            html += '</ol>\n'
                        html += '<ul class="dot-list">\n'
                        current_list_type = 'ul'
                    processed_line = process_bold_text(line[2:])
                    processed_line = process_image(processed_line)
                    html += f'<li class="dot-item">{processed_line}</li>\n'
                elif line.startswith('* '):
                    if current_list_type != 'ul':
                        if current_list_type == 'ol':
                            html += '</ol>\n'
                        html += '<ul class="dot-list">\n'
                        current_list_type = 'ul'
                    processed_line = process_bold_text(line[2:])
                    processed_line = process_image(processed_line)
                    html += f'<li class="star-item">{processed_line}</li>\n'
                elif any(line.strip().startswith(f'{i}.') for i in range(1, 10)):
                    if current_list_type != 'ol':
                        if current_list_type == 'ul':
                            html += '</ul>\n'
                        html += '<ol>\n'
                        current_list_type = 'ol'
                    number = line.split('.', 1)[0]
                    processed_line = process_bold_text(line.split(".", 1)[1].strip())
                    processed_line = process_image(processed_line)
                    html += f'<li value="{number}">{processed_line}</li>\n'
                else:
                    if current_list_type:
                        if current_list_type == 'ol':
                            html += '</ol>\n'
                        elif current_list_type == 'ul':
                            html += '</ul>\n'
                        current_list_type = None
                    processed_line = process_bold_text(line.strip())
                    processed_line = process_image(processed_line)
                    html += f'<p>{processed_line}</p>\n'
        
        if current_list_type:
            if current_list_type == 'ol':
                html += '</ol>\n'
            elif current_list_type == 'ul':
                html += '</ul>\n'
        
        html += '</div>\n'
        html += '</div>\n'
    
    return html

def process_subsection(title, content):
    """Process a subsection with subtitle-details structure"""
    html = f'<div class="subtitle-details">\n'
    
    # Get text after ### as title
    if title.startswith('### '):
        title = title[4:]  # Remove ###
    
    def process_bold_text(text):
        """Convert **text** to <strong>text</strong>"""
        processed_text = text
        while '**' in processed_text:
            start = processed_text.find('**')
            end = processed_text.find('**', start + 2)
            if end != -1:
                bold_text = processed_text[start+2:end]
                processed_text = processed_text[:start] + f'<strong>{bold_text}</strong>' + processed_text[end+2:]
            else:
                break
        return processed_text

    def process_image(text):
        """Convert ![alt](url) to <img> tag"""
        if '![' in text and '](' in text:
            alt_start = text.find('![') + 2
            alt_end = text.find(']', alt_start)
            url_start = text.find('(', alt_end) + 1
            url_end = text.find(')', url_start)
            
            if alt_end != -1 and url_end != -1:
                alt_text = text[alt_start:alt_end]
                url = text[url_start:url_end]
                return f'<img src="{url}" alt="{alt_text}" class="markdown-image">'
        return text
    
    html += f'<div class="body">\n'
    html += f'<h3>{process_bold_text(title)}</h3>\n'
    
    current_list_type = None
    for line in content:
        if line.strip():
            if line.startswith('- '):
                if current_list_type != 'ul':
                    if current_list_type == 'ol':
                        html += '</ol>\n'
                    html += '<ul class="dot-list">\n'
                    current_list_type = 'ul'
                processed_line = process_bold_text(line[2:])
                processed_line = process_image(processed_line)
                html += f'<li class="dot-item">{processed_line}</li>\n'
            elif line.startswith('* '):
                if current_list_type != 'ul':
                    if current_list_type == 'ol':
                        html += '</ol>\n'
                    html += '<ul class="dot-list">\n'
                    current_list_type = 'ul'
                processed_line = process_bold_text(line[2:])
                processed_line = process_image(processed_line)
                html += f'<li class="star-item">{processed_line}</li>\n'
            elif any(line.strip().startswith(f'{i}.') for i in range(1, 10)):
                if current_list_type != 'ol':
                    if current_list_type == 'ul':
                        html += '</ul>\n'
                    html += '<ol>\n'
                    current_list_type = 'ol'
                number = line.split('.', 1)[0]
                processed_line = process_bold_text(line.split(".", 1)[1].strip())
                processed_line = process_image(processed_line)
                html += f'<li value="{number}">{processed_line}</li>\n'
            else:
                if current_list_type:
                    if current_list_type == 'ol':
                        html += '</ol>\n'
                    elif current_list_type == 'ul':
                        html += '</ul>\n'
                    current_list_type = None
                processed_line = process_bold_text(line.strip())
                processed_line = process_image(processed_line)
                html += f'<p>{processed_line}</p>\n'
    
    if current_list_type:
        if current_list_type == 'ol':
            html += '</ol>\n'
        elif current_list_type == 'ul':
            html += '</ul>\n'
    
    html += '</div>\n'
    html += '</div>\n'
    
    return html