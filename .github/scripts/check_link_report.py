"""Keep network outages visible without treating them as proven broken links."""

import html
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def annotation(level, message):
    message = str(message).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    print(f'::{level}::{message}')


def cell(value):
    return html.escape(str(value)).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')


def evaluate(report, exit_code):
    if exit_code not in {'0', '2'}:
        raise ValueError(f'lychee could not complete (exit code {exit_code!r})')
    if not isinstance(report, dict):
        raise ValueError('Report must be a JSON object')
    for field in ('total', 'successful', 'excludes', 'errors', 'timeouts'):
        if type(report.get(field)) is not int or report[field] < 0:
            raise ValueError(f'Missing or invalid report field: {field}')
    if report['total'] == 0 or report['total'] <= report['excludes']:
        raise ValueError('No links were actually checked')

    broken, unverified = [], []
    for field in ('error_map', 'timeout_map'):
        entries = report.get(field)
        if not isinstance(entries, dict):
            raise ValueError(f'Missing or invalid report field: {field}')
        for source, responses in entries.items():
            if not isinstance(responses, list):
                raise ValueError(f'Invalid response list in {field}')
            for response in responses:
                url = response['url']
                status = response['status']
                text = status['text']
                code = status.get('code')
                external = urlsplit(url).scheme in {'http', 'https'}
                network_failure = external and (
                    field == 'timeout_map'
                    or (code is None and text.startswith('Network error:'))
                )
                entry = (source, url, text)
                (unverified if network_failure else broken).append(entry)

    if (report['errors'] or report['timeouts'] or exit_code == '2') and not (broken or unverified):
        raise ValueError('lychee failed without reporting the affected links')
    return broken, unverified


def main():
    try:
        report = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        broken, unverified = evaluate(report, os.environ.get('LYCHEE_EXIT_CODE', ''))
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        annotation('error', f'Link checker/report failure: {error}')
        return 1

    lines = [
        '## Link check',
        '',
        f"Checked {report['total']} links: {report['successful']} successful, "
        f"{report['excludes']} excluded, {len(broken)} broken, "
        f'{len(unverified)} unverified due to network errors.',
        '',
    ]
    for title, entries, level in (
        ('Broken links — action required', broken, 'error'),
        ('Network errors — retry or verify manually', unverified, 'warning'),
    ):
        if not entries:
            continue
        lines += [f'### {title}', '', '| Source | URL | Result |', '|---|---|---|']
        for source, url, text in sorted(entries):
            annotation(level, f'{source}: {url} — {text}')
            lines.append('| ' + ' | '.join(cell(value) for value in (source, url, text)) + ' |')
        lines.append('')
    if unverified:
        lines += ['Network errors do not prove a link is valid. Repeated warnings need manual review.', '']
    summary = '\n'.join(lines)
    print(summary)
    if path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(path, 'a', encoding='utf-8') as output:
            output.write(summary + '\n')
    return int(bool(broken))


if __name__ == '__main__':
    sys.exit(main())
