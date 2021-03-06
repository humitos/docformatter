#!/usr/bin/env python
#
# Copyright (C) 2012-2015 Steven Myint
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Formats docstrings to follow PEP 257."""

from __future__ import (absolute_import,
                        division,
                        print_function,
                        unicode_literals)

import io
import locale
import os
import re
import signal
import sys
import textwrap
import tokenize

import untokenize


__version__ = '0.7.1'


try:
    unicode
except NameError:
    unicode = str


def format_code(source, **kwargs):
    """Return source code with docstrings formatted.

    Wrap summary lines if summary_wrap_length is greater than 0.

    See "_format_code()" for parameters.

    """
    try:
        return _format_code(source, **kwargs)
    except (tokenize.TokenError, IndentationError):
        return source


def _format_code(source,
                 summary_wrap_length=79,
                 description_wrap_length=72,
                 pre_summary_newline=False,
                 make_summary_multiline=False,
                 post_description_blank=True,
                 force_wrap=False,
                 line_range=None):
    """Return source code with docstrings formatted."""
    if not source:
        return source

    if line_range is not None:
        assert line_range[0] > 0 and line_range[1] > 0

    def in_range(start, end):
        """Return True if start/end is in line_range."""
        if line_range is None:
            return True
        return any(line_range[0] <= line_no <= line_range[1]
                   for line_no in range(start, end + 1))

    modified_tokens = []

    sio = io.StringIO(source)
    previous_token_string = ''
    previous_token_type = None
    only_comments_so_far = True

    for (token_type,
         token_string,
         start,
         end,
         line) in tokenize.generate_tokens(sio.readline):

        if (
            token_type == tokenize.STRING and
            token_string.startswith(('"', "'")) and
            (previous_token_type == tokenize.INDENT or
                only_comments_so_far) and
            in_range(start[0], end[0])
        ):
            if only_comments_so_far:
                indentation = ''
            else:
                indentation = previous_token_string

            token_string = format_docstring(
                indentation,
                token_string,
                summary_wrap_length=summary_wrap_length,
                description_wrap_length=description_wrap_length,
                pre_summary_newline=pre_summary_newline,
                make_summary_multiline=make_summary_multiline,
                post_description_blank=post_description_blank,
                force_wrap=force_wrap)

        if token_type not in [tokenize.COMMENT, tokenize.NEWLINE, tokenize.NL]:
            only_comments_so_far = False

        previous_token_string = token_string
        previous_token_type = token_type

        modified_tokens.append(
            (token_type, token_string, start, end, line))

    return untokenize.untokenize(modified_tokens)


def format_docstring(indentation, docstring,
                     summary_wrap_length=0,
                     description_wrap_length=0,
                     pre_summary_newline=False,
                     make_summary_multiline=False,
                     post_description_blank=True,
                     force_wrap=False):
    """Return formatted version of docstring.

    Wrap summary lines if summary_wrap_length is greater than 0.

    Relevant parts of PEP 257:
        - For consistency, always use triple double quotes around docstrings.
        - Triple quotes are used even though the string fits on one line.
        - Multi-line docstrings consist of a summary line just like a one-line
          docstring, followed by a blank line, followed by a more elaborate
          description.
        - The BDFL recommends inserting a blank line between the last paragraph
          in a multi-line docstring and its closing quotes, placing the closing
          quotes on a line by themselves.

    """
    contents = strip_docstring(docstring)

    # Skip if there are nested triple double quotes
    if contents.count('"""'):
        return docstring

    # Do not modify things that start with doctests.
    if contents.lstrip().startswith('>>>'):
        return docstring

    summary, description = split_summary_and_description(contents)

    # Leave docstrings with underlined summaries alone.
    if remove_section_header(description).strip() != description.strip():
        return docstring

    if not force_wrap and is_some_sort_of_list(summary):
        # Something is probably not right with the splitting.
        return docstring

    if description:
        # Compensate for triple quotes by temporarily prepending 3 spaces.
        # This temporary prepending is undone below.
        if pre_summary_newline:
            initial_indent = indentation
        else:
            initial_indent = 3 * ' ' + indentation

        return '''\
"""{pre_summary}{summary}

{description}{post_description}
{indentation}"""\
'''.format(
            pre_summary=('\n' + indentation if pre_summary_newline
                         else ''),
            summary=wrap_summary(normalize_summary(summary),
                                 wrap_length=summary_wrap_length,
                                 initial_indent=initial_indent,
                                 subsequent_indent=indentation).lstrip(),
            description=wrap_description(description,
                                         indentation=indentation,
                                         wrap_length=description_wrap_length,
                                         force_wrap=force_wrap),
            post_description=('\n' if post_description_blank else ''),
            indentation=indentation)
    else:
        beginning = '"""'
        ending = '"""'
        if make_summary_multiline:
            beginning = beginning + '\n' + indentation
            ending = '\n' + indentation + ending
            summary_wrapped = wrap_summary(normalize_summary(contents),
                                           wrap_length=summary_wrap_length,
                                           initial_indent=indentation,
                                           subsequent_indent=indentation).strip()
            return '{beginning}{summary}{ending}'.format(
                beginning=beginning,
                summary=summary_wrapped,
                ending=ending
            )
        else:
            return wrap_summary('"""' + normalize_summary(contents) + '"""',
                                wrap_length=summary_wrap_length,
                                initial_indent=indentation,
                                subsequent_indent=indentation).strip()


def reindent(text, indentation):
    """Return reindented text that matches indentation."""
    if '\t' not in indentation:
        text = text.expandtabs()

    text = textwrap.dedent(text)

    return '\n'.join(
        [(indentation + line).rstrip()
         for line in text.splitlines()]).rstrip() + '\n'


def is_probably_beginning_of_sentence(line):
    """Return True if this line begins a new sentence."""
    # Check heuristically for a parameter list.
    for token in ['@', '-', r'\*']:
        if re.search(r'\s' + token + r'\s', line):
            return True

    return re.match(r'[^\w"\'`\(\)]', line.strip())


def split_summary_and_description(contents):
    """Split docstring into summary and description.

    Return tuple (summary, description).

    """
    split_lines = contents.rstrip().splitlines()

    for index in range(1, len(split_lines)):
        found = False

        if not split_lines[index].strip():
            # Empty line separation would indicate the rest is the description.
            found = True
        elif is_probably_beginning_of_sentence(split_lines[index]):
            # Symbol on second line probably is a description with a list.
            found = True

        if found:
            return ('\n'.join(split_lines[:index]).strip(),
                    '\n'.join(split_lines[index:]).rstrip())

    # Break on first sentence.
    split = split_first_sentence(contents)
    if split[0].strip() and split[1].strip():
        return (
            split[0].strip(),
            _find_shortest_indentation(
                split[1].splitlines()[1:]) + split[1].strip()
        )

    return (contents, '')


def split_first_sentence(text):
    """Split text into first sentence and the rest.

    Return a tuple (sentence, rest).

    """
    sentence = ''
    rest = text
    delimiter = ''
    previous_delimiter = ''

    while rest:
        split = re.split(r'(\s)', rest, maxsplit=1)
        if len(split) == 3:
            word = split[0]
            delimiter = split[1]
            rest = split[2]
        else:
            assert len(split) == 1
            word = split[0]
            delimiter = ''
            rest = ''

        sentence += previous_delimiter + word

        if sentence.endswith(('e.g.', 'i.e.',
                              'Dr.',
                              'Mr.', 'Mrs.', 'Ms.')):
            # Ignore false end of sentence.
            pass
        elif sentence.endswith(('.', '?', '!')):
            break
        elif sentence.endswith(':') and delimiter == '\n':
            # Break on colon if it ends the line. This is a heuristic to detect
            # the beginning of some parameter list afterwards.
            break

        previous_delimiter = delimiter
        delimiter = ''

    return (sentence, delimiter + rest)


def is_some_sort_of_list(text):
    """Return True if text looks like a list."""
    split_lines = text.rstrip().splitlines()
    if len(split_lines) > max([len(line.strip()) for line in split_lines] +
                              [0]):
        return True

    return (
        re.search(r'\n\s*\n', text) or
        re.search(r'[0-9]\.', text) or
        re.search(r'[\-*:=@]', text)
    )


def _find_shortest_indentation(lines):
    """Return most shortest indentation."""
    assert not isinstance(lines, str)

    indentation = None

    for line in lines:
        if line.strip():
            non_whitespace_index = len(line) - len(line.lstrip())
            _indent = line[:non_whitespace_index]
            if indentation is None or len(_indent) < len(indentation):
                indentation = _indent

    return indentation or ''


def strip_docstring(docstring):
    """Return contents of docstring."""
    docstring = docstring.strip()

    if docstring.startswith("'''"):
        quote = "'''"
    elif docstring.startswith('"""'):
        quote = '"""'
    elif docstring.startswith("'"):
        quote = "'"
    elif docstring.startswith('"'):
        quote = '"'
    else:
        raise ValueError('We only handle strings that start with quotes')

    assert docstring.endswith(quote)

    return docstring.split(quote, 1)[1].rsplit(quote, 1)[0].strip()


def normalize_summary(summary):
    """Return normalized docstring summary."""
    # Remove newlines
    summary = re.sub(r'\s*\n\s*', ' ', summary.rstrip())

    # Add period at end of sentence
    if summary and (summary[-1].isalnum() or summary[-1] in ['"', "'"]):
        summary += '.'

    return summary


def wrap_summary(summary, initial_indent, subsequent_indent, wrap_length):
    """Return line-wrapped summary text."""
    if wrap_length > 0:
        return '\n'.join(
            textwrap.wrap(summary,
                          width=wrap_length,
                          initial_indent=initial_indent,
                          subsequent_indent=subsequent_indent)).strip()
    else:
        return summary


def wrap_description(text, indentation, wrap_length, force_wrap):
    """Return line-wrapped description text.

    We only wrap simple descriptions. We leave doctests, multi-paragraph text,
    and bulleted lists alone.

    """
    text = strip_leading_blank_lines(text)

    # Do not modify doctests at all.
    if '>>>' in text:
        return text

    text = reindent(text, indentation).rstrip()

    # Ignore possibly complicated cases.
    if wrap_length <= 0 or (not force_wrap and is_some_sort_of_list(text)):
        return text

    return indentation + '\n'.join(
        textwrap.wrap(textwrap.dedent(text),
                      width=wrap_length,
                      initial_indent=indentation,
                      subsequent_indent=indentation)).strip()


def remove_section_header(text):
    r"""Return text with section header removed.

    >>> remove_section_header('----\nfoo\nbar\n')
    'foo\nbar\n'

    >>> remove_section_header('===\nfoo\nbar\n')
    'foo\nbar\n'

    """
    stripped = text.lstrip()
    if not stripped:
        return text

    first = stripped[0]
    if (
        not first.isalnum() and
        not first.isspace() and
        not stripped.splitlines()[0].strip(first).strip()
    ):
        return stripped.lstrip(first).lstrip()

    return text


def strip_leading_blank_lines(text):
    """Return text with leading blank lines removed."""
    split = text.splitlines()

    found = 0
    for index, line in enumerate(split):
        if line.strip():
            found = index
            break

    return '\n'.join(split[found:])


def open_with_encoding(filename, encoding, mode='r'):
    """Return opened file with a specific encoding."""
    return io.open(filename, mode=mode, encoding=encoding,
                   newline='')  # Preserve line endings


def detect_encoding(filename):
    """Return file encoding."""
    try:
        with open(filename, 'rb') as input_file:
            from lib2to3.pgen2 import tokenize as lib2to3_tokenize
            encoding = lib2to3_tokenize.detect_encoding(input_file.readline)[0]

            # Check for correctness of encoding.
            with open_with_encoding(filename, encoding) as input_file:
                input_file.read()

        return encoding
    except (SyntaxError, LookupError, UnicodeDecodeError):
        return 'latin-1'


def format_file(filename, args, standard_out):
    """Run format_code() on a file."""
    encoding = detect_encoding(filename)
    with open_with_encoding(filename, encoding=encoding) as input_file:
        source = input_file.read()
        formatted_source = _format_code_with_args(source, args)

    if source != formatted_source:
        if args.in_place:
            with open_with_encoding(filename, mode='w',
                                    encoding=encoding) as output_file:
                output_file.write(formatted_source)
        else:
            import difflib
            diff = difflib.unified_diff(
                source.splitlines(),
                formatted_source.splitlines(),
                'before/' + filename,
                'after/' + filename,
                lineterm='')
            standard_out.write('\n'.join(list(diff) + ['']))


def _format_code_with_args(source, args):
    """Run format_code with parsed command-line arguments."""
    return format_code(
        source,
        summary_wrap_length=args.wrap_summaries,
        description_wrap_length=args.wrap_descriptions,
        pre_summary_newline=args.pre_summary_newline,
        make_summary_multiline=args.make_summary_multiline,
        post_description_blank=args.post_description_blank,
        force_wrap=args.force_wrap,
        line_range=args.line_range)


def _main(argv, standard_out, standard_error, standard_in):
    """Internal main entry point."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, prog='docformatter')
    parser.add_argument('-i', '--in-place', action='store_true',
                        help='make changes to files instead of printing diffs')
    parser.add_argument('-r', '--recursive', action='store_true',
                        help='drill down directories recursively')
    parser.add_argument('--wrap-summaries', default=79, type=int,
                        metavar='length',
                        help='wrap long summary lines at this length '
                             '(default: %(default)s)')
    parser.add_argument('--wrap-descriptions', default=72, type=int,
                        metavar='length',
                        help='wrap descriptions at this length '
                             '(default: %(default)s)')
    parser.add_argument('--no-blank', dest='post_description_blank',
                        action='store_false',
                        help='do not add blank line after description')
    parser.add_argument('--pre-summary-newline',
                        action='store_true',
                        help='add a newline before the summary of a '
                             'multi-line docstring')
    parser.add_argument('--make-summary-multiline',
                        action='store_true',
                        help='add a newline before and after the summary of a '
                             'one-line docstring')
    parser.add_argument('--force-wrap', action='store_true',
                        help='force descriptions to be wrapped even if it may '
                             'result in a mess')
    parser.add_argument('--range', metavar='line', dest='line_range',
                        default=None, type=int, nargs=2,
                        help='apply docformatter to docstrings between these '
                             'lines; line numbers are indexed at 1')
    parser.add_argument('--version', action='version',
                        version='%(prog)s ' + __version__)
    parser.add_argument('files', nargs='+',
                        help="files to format or '-' for standard in")

    args = parser.parse_args(argv[1:])

    if args.line_range:
        if args.line_range[0] <= 0:
            parser.error('--range must be positive numbers')
        if args.line_range[0] > args.line_range[1]:
            parser.error('First value of --range should be less than or equal '
                         'to the second')

    if '-' in args.files:
        _format_standard_in(args,
                            parser=parser,
                            standard_out=standard_out,
                            standard_in=standard_in)
    else:
        _format_files(args,
                      standard_out=standard_out,
                      standard_error=standard_error)


def _format_standard_in(args, parser, standard_out, standard_in):
    """Print formatted text to standard out."""
    if len(args.files) > 1:
        parser.error('cannot mix standard in and regular files')

    if args.in_place:
        parser.error('--in-place cannot be used with standard input')

    if args.recursive:
        parser.error('--recursive cannot be used with standard input')

    encoding = None
    source = standard_in.read()

    if not isinstance(source, unicode):
        encoding = standard_in.encoding or _get_encoding()
        source = source.decode(encoding)

    formatted_source = _format_code_with_args(source, args=args)
    if encoding:
        formatted_source = formatted_source.encode(encoding)

    standard_out.write(formatted_source)


def _get_encoding():
    """Return preferred encoding."""
    return locale.getpreferredencoding() or sys.getdefaultencoding()


def _format_files(args, standard_out, standard_error):
    """Format multiple files."""
    filenames = list(set(args.files))
    while filenames:
        name = filenames.pop(0)
        if args.recursive and os.path.isdir(name):
            for root, directories, children in os.walk(unicode(name)):
                filenames += [os.path.join(root, f) for f in children
                              if f.endswith('.py') and
                              not f.startswith('.')]
                directories[:] = [d for d in directories
                                  if not d.startswith('.')]
        else:
            try:
                format_file(name, args=args, standard_out=standard_out)
            except IOError as exception:
                print(unicode(exception), file=standard_error)


def main():
    """Main entry point."""
    try:
        # Exit on broken pipe.
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except AttributeError:  # pragma: no cover
        # SIGPIPE is not available on Windows.
        pass

    try:
        return _main(sys.argv,
                     standard_out=sys.stdout,
                     standard_error=sys.stderr,
                     standard_in=sys.stdin)
    except KeyboardInterrupt:
        return 2  # pragma: no cover


if __name__ == '__main__':
    sys.exit(main())
