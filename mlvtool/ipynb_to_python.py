#!/usr/bin/env python3
import argparse
import logging
from collections import namedtuple
from os import makedirs
from os.path import abspath, exists
from os.path import realpath, dirname, join
from typing import List

from nbconvert import PythonExporter
from nbformat import NotebookNode

from mlvtool.cmd import CommandHelper, ArgumentBuilder
from mlvtool.conf.conf import get_script_output_path, load_conf_or_default, MlVToolConf, get_conf_file_default_path, \
    DEFAULT_IGNORE_KEY, get_work_directory
from mlvtool.docstring_helpers.extract import extract_docstring
from mlvtool.docstring_helpers.parse import parse_docstring
from mlvtool.exception import MlVToolException
from mlvtool.helper import to_method_name

logging.getLogger().setLevel(logging.INFO)
CURRENT_DIR = realpath(dirname(__file__))
TEMPLATE_PATH = join(CURRENT_DIR, '..', 'template', 'ml-python.pl')

DocstringWrapper = namedtuple('DocstringWrapper',
                              ('docstring', 'params'))


def get_config(template_path: str) -> dict:
    return {'TemplateExporter': {'template_file': template_path},
            'NbConvertApp': {'export_format': 'python'}}


def export(input_notebook_path: str, output_path: str, conf: MlVToolConf):
    """
        Export a    notebook to a parameterize Python 3 script
        using jinja templates
    """
    exporter = PythonExporter(get_config(TEMPLATE_PATH))
    exporter.register_filter(name='extract_docstring_and_param',
                             jinja_filter=extract_docstring_and_param)
    exporter.register_filter(name='filter_no_effect',
                             jinja_filter=filter_no_effect)
    exporter.register_filter(name='handle_params',
                             jinja_filter=handle_params)
    exporter.register_filter(name='sanitize_method_name',
                             jinja_filter=to_method_name)
    resources = {'ignore_keys': conf.ignore_keys}
    try:
        output_script, _ = exporter.from_filename(input_notebook_path, resources=resources)
    except Exception as e:
        raise MlVToolException(e) from e

    if not output_script:
        logging.warning('Empty notebook provided. Nothing to do.')
        return
    makedirs(dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as fd:
        fd.write(output_script)


def get_param_as_python_method_format(docstring_str: str) -> str:
    """
        Extract parameters from a docstring then format them
    """
    docstring_data = parse_docstring(docstring_str)
    params = ['{}{}'.format(p.arg_name, '' if not p.type_name else f': {p.type_name}')
              for p in docstring_data.params]
    return ', '.join(params)


def extract_docstring_and_param(cell_content: str) -> DocstringWrapper:
    """
        Extract docstring and formatted parameters from a cell content
    """
    docstring = extract_docstring(cell_content)
    if not docstring:
        logging.warning("Docstring not found.")
    params = get_param_as_python_method_format(docstring)
    return DocstringWrapper(f'"""\n{docstring}\n"""', params)


def handle_params(cells: List[NotebookNode]):
    """
        Extract parameters from the first code cell and remove it
    """
    try:
        first_code_cell = next(cell for cell in cells if is_code_cell(cell))
    except StopIteration:
        logging.warning('No code cell found.')
        return DocstringWrapper([], '')
    docstring_wrapper = extract_docstring_and_param(first_code_cell.source)
    if docstring_wrapper.params:
        cells.remove(first_code_cell)
    return docstring_wrapper


def filter_no_effect(cell_content: str, resource: dict) -> str:
    """
        Filter cell with no effect statement
    """
    for keyword in resource.get('ignore_keys', [DEFAULT_IGNORE_KEY]):
        if keyword in cell_content:
            logging.warning('Discard cell with no effect')
            return ''
    return cell_content


def is_code_cell(cell: NotebookNode) -> bool:
    return cell.cell_type == 'code'


class IPynbToPython(CommandHelper):

    def run(self, *args, **kwargs):
        args = ArgumentBuilder(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
                               description='Convert Notebook to python script') \
            .add_work_dir_argument() \
            .add_conf_path_argument() \
            .add_force_argument() \
            .add_argument('-n', '--notebook', type=str, required=True,
                          help='The notebook to convert') \
            .add_argument('-o', '--output', type=str,
                          help='The Python script output path') \
            .parse(args)
        work_directory = args.working_directory or get_work_directory(args.notebook)
        conf_path = args.conf_path or get_conf_file_default_path(work_directory)
        conf = load_conf_or_default(conf_path, work_directory)

        if not conf.path and not args.output:
            raise MlVToolException('Parameter --output is mandatory if no conf provided')

        output = args.output or get_script_output_path(args.notebook, conf)

        if not args.force and exists(output):
            raise MlVToolException(f'Output file {output} already exists, use --force option to overwrite it')

        export(args.notebook, output, conf)
        logging.info(f'Python script generated in {abspath(output)}')
