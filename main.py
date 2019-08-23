#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import subprocess
import sys
import os
import shutil
import re
import nltk
import platform
import cursor
import time
import logging
from dataclasses import dataclass
from html.parser import HTMLParser


class WiseException(Exception):
    def __init__(self, message, desc):
        super().__init__(message)

        self.desc = desc


def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.realpath(__file__))

    return os.path.join(base_path, relative_path)


# Got it from https://gist.github.com/aubricus/f91fb55dc6ba5557fbab06119420dd6a
# Print iterations progress
def print_progress(iteration, total, prefix='', suffix='', decimals=1, bar_length=100):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        bar_length  - Optional  : character length of bar (Int)
    """
    if iteration == 0:
        cursor.hide()

    bar_length = shutil.get_terminal_size()[0] // 2

    str_format = "{0:." + str(decimals) + "f}"
    percents = str_format.format(100 * (iteration / float(total)))
    filled_length = int(round(bar_length * iteration / float(total)))
    bar = '+' * filled_length + '-' * (bar_length - filled_length)

    progress_bar = "\r%s |%s| %s%s %s" % (prefix, bar, percents, '%', suffix)

    print(progress_bar, end='', flush=True)

    if iteration == total:
        print("")
        cursor.show()


def usage():
    print("./main.py input_book")


class WordFilter:
    def __init__(self):
        filter_path = get_resource_path("filter.txt")
        with open(filter_path, 'rt') as f:
            self.do_not_take = []
            for line in f:
                if line.strip()[0] == '#':
                    continue
                word = line.strip()
                self.do_not_take.append(word)

    def is_take_word(self, word):
        lword = word.lower()

        if word in self.do_not_take:
            return False

        # Do not take words with contractions
        # like "tree's", "he'll", "we've", e.t.c
        if word.find('\'') != -1:
            return False

        return True


class LanguageLayerDB():
    def __init__(self, path_to_dir, book_asin):
        self.asin = book_asin
        self.conn = None
        self.cursor = None
        self.path_to_dir = path_to_dir
        self.open_db()
        try:
            query = "CREATE TABLE glosses (start INTEGER PRIMARY KEY, end INTEGER, difficulty INTEGER, sense_id INTEGER, low_confidence BOOLEAN)"
            r = self.cursor.execute(query)
            query = "CREATE TABLE metadata (key TEXT, value TEXT)"
            r = self.cursor.execute(query)
        except sqlite3.Error as e:
            print(e)

        en_dictionary_version = "2016-09-14"
        en_dictionary_revision = '57'
        en_dictionary_id = 'kll.en.en'

        metadata = {
            'acr': 'CR!W0W520HKPX6X12GRQ87AQC3XW3BV',
            'targetLanguages': 'en',
            'sidecarRevision': '45',
            'ftuxMarketplaces': 'ATVPDKIKX0DER,A1F83G8C2ARO7P,A39IBJ37TRP1C6,A2EUQ1WTGCTBG2',
            'bookRevision': 'b5320927',
            'sourceLanguage': 'en',
            'enDictionaryVersion': en_dictionary_version,
            'enDictionaryRevision': en_dictionary_revision,
            'enDictionaryId': en_dictionary_id,
            'sidecarFormat': '1.0',
        }

        try:
            for key, value in metadata.items():
                query = "INSERT INTO metadata VALUES (?, ?)"
                r = self.cursor.execute(query, (key, value))
            self.conn.commit()
        except sqlite3.Error as e:
            print(e)

    def open_db(self):
        if self.conn == None:
            db_name = "LanguageLayer.en.{}.kll".format(self.asin)
            path_to_db = os.path.join(self.path_to_dir, db_name)
            self.conn = sqlite3.connect(path_to_db)
            self.cursor = self.conn.cursor()

    def close_db(self):
        self.conn.close()
        self.conn = None

    def start_transaction(self):
        self.cursor.execute("BEGIN TRANSACTION")

    def end_transaction(self):
        self.conn.commit()

    def add_gloss(self, start, difficulty, sense_id):
        self.open_db()
        try:
            query = "INSERT INTO glosses VALUES (?,?,?,?,?)"
            new_gloss = (start, None, difficulty, sense_id, 0)
            self.cursor.execute(query, new_gloss)
        except sqlite3.Error as e:
            pass


@dataclass
class Gloss:
    offset: int
    word: str


class RawmlRarser(HTMLParser):
    def __init__(self, book_content, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bt = book_content
        self.result = []
        self.wf = WordFilter()
        self.last_token_offset = 0
        self.last_token_bt_offset = 0

    def parse(self):
        self.feed(self.bt)
        return self.result

    def handle_starttag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        pass

    def handle_data(self, data):
        paragraph_text = data
        for match in re.finditer(r'[A-Za-z\']+', paragraph_text):
            word = paragraph_text[match.start():match.end()]
            if self.wf.is_take_word(word):
                word_offset = self.getpos()[1] + match.start()
                word_byte_offset = self.last_token_bt_offset + len(
                    self.bt[self.last_token_offset:word_offset].encode('utf-8'))
                self.last_token_offset = word_offset
                self.last_token_bt_offset = word_byte_offset
                self.result.append(Gloss(offset=word_byte_offset, word=word))


def get_path_to_mobitool():
    path_to_third_party = get_resource_path("third_party")

    if platform.system() == "Linux":
        path_to_mobitool = os.path.join(path_to_third_party, "mobitool-linux-i386")
    if platform.system() == "Windows":
        path_to_mobitool = os.path.join(path_to_third_party, "mobitool-win32.exe")
    if platform.system() == "Darwin":
        path_to_mobitool = os.path.join(path_to_third_party, "mobitool-osx-x86_64")

    return path_to_mobitool


def get_book_asin(path_to_book):
    path_to_mobitool = get_path_to_mobitool()

    command = [path_to_mobitool, path_to_book]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        out, err = proc.communicate()
    except Exception as e:
        command_str = " ".join(command)
        description = ["Failed to run command", command_str, e]
        raise WiseException("", description)

    try:
        book_metadata = out.decode("utf-8")
        match = re.search("ASIN: (\S+)", book_metadata)
        if match:
            book_asin = match.group(1)
            return book_asin
        else:
            return None
    except Exception as e:
        message = ["Failed to decode mobitool output"]
        raise WiseException("", message)


def get_rawml_content(path_to_book):
    path_to_mobitool = get_path_to_mobitool()

    command = [path_to_mobitool, '-d', path_to_book]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE)
        out, err = proc.communicate()
    except Exception as e:
        command_str = " ".join(command)
        description = ["Failed to run command", command_str, e]
        raise WiseException("", description)

    try:
        book_name = os.path.basename(path_to_book)
        book_name_without_ex = os.path.splitext(book_name)[0]
        rawml_name = "{}.rawml".format(book_name_without_ex)
        path_to_rawml = os.path.join(os.path.dirname(path_to_book), rawml_name)
        with open(path_to_rawml, 'rt', encoding='utf-8') as f:
            book_content = f.read()
        os.remove(path_to_rawml)
        return book_content
    except UnicodeDecodeError as e:
        message = ["Failed to open {} - {}".format(path_to_rawml, e)]
        raise WiseException("", message)


def check_dependencies():
    try:
        subprocess.check_output('ebook-convert --version', shell=True)
    except FileNotFoundError as e:
        raise ValueError("Calibre not found")

    path_to_nltk = get_resource_path("nltk_data")
    if not os.path.exists(path_to_nltk):
        raise ValueError(path_to_nltk + " not found")

    path_to_mobitool = get_path_to_mobitool()
    if not os.path.exists(path_to_mobitool):
        raise ValueError(path_to_mobitool + " not found")


def get_glosses(path_to_book):
    print("[.] Getting rawml content of the book")
    try:
        book_content = get_rawml_content(path_to_book)
    except WiseException as e:
        print("  [-] Can't get rawml content:")
        print("    |", e)
        raise ValueError()

    print("[.] Collecting words")
    parser = RawmlRarser(book_content)
    words = parser.parse()
    return words


def get_or_create_book_asin(path_to_book):
    print("[.] Converting mobi 2 mobi to generate ASIN")
    # Convert mobi to mobi by calibre and get ASIN that calibre assign to converted book
    try:
        converted_book_path = os.path.join(os.path.dirname(path_to_book),
                                           "tmp_book_{}".format(os.path.basename(path_to_book)))

        cmd_str = "{} \"{}\" \"{}\"".format('ebook-convert', path_to_book, converted_book_path)
        out = subprocess.check_output(cmd_str, shell=True)

        shutil.move(converted_book_path, path_to_book)
    except Exception as e:
        print("  [-] Failed to convert mobi 2 mobi:")
        print("    |", e)
        raise ValueError()

    print("[.] Getting ASIN")
    try:
        book_asin = get_book_asin(path_to_book)
    except WiseException as e:
        print("  [-] Can't get ASIN:")
        for item in e.desc:
            print("    |", item)
        raise ValueError()

    return book_asin


def get_explanatory_dictionary():
    result = {}
    senses_path = get_resource_path("senses.csv")
    with open(senses_path, 'rb') as f:
        f = f.read().decode('utf-8')
        for line in f.splitlines():
            l = line.strip()
            if l[0] == '"':
                continue
            word, sense_id, difficulty = l.split(',')
            result[word] = [sense_id, difficulty]
    return result


def get_logger_for_words():
    wlog = logging.getLogger('word-processing')
    wlog.setLevel(logging.INFO)
    fh = logging.FileHandler('log-result-word-meanings.txt')
    wlog.addHandler(fh)
    return wlog


class WordProcessor:
    def __init__(self, path_to_nltk_data):
        nltk.data.path = [path_to_nltk_data] + nltk.data.path
        self.lemmatizer = nltk.WordNetLemmatizer()

    def normalize_word(self, word):
        word = word.lower()
        pos_tag = nltk.pos_tag([word])[0][1]
        pos_tag_wordnet = self.get_wordnet_pos(pos_tag)
        return self.lemmatizer.lemmatize(word, pos=pos_tag_wordnet)

    def get_wordnet_pos(self, treebank_tag):
        if treebank_tag.startswith('J'):
            return nltk.corpus.wordnet.ADJ
        elif treebank_tag.startswith('V'):
            return nltk.corpus.wordnet.VERB
        elif treebank_tag.startswith('N'):
            return nltk.corpus.wordnet.NOUN
        elif treebank_tag.startswith('R'):
            return nltk.corpus.wordnet.ADV
        else:
            return nltk.corpus.wordnet.NOUN


class WWResult:
    def __init__(self, input_path, output_path):
        if not os.path.exists(input_path):
            print("[-] Wrong path to book: {}".format(input_path))

        self._input_file_name = os.path.basename(input_path)
        self._output_path = output_path

        self.book_name = os.path.splitext(self._input_file_name)[0]
        self.result_dir_path = self._get_result_dir_path()
        self.book_path = os.path.join(self.result_dir_path, self._input_file_name)

        shutil.copyfile(input_path, self.book_path)

    def _get_result_dir_path(self):
        dir_name = "{}-WordWised".format(self.book_name)
        result = os.path.join(self._output_path, dir_name)

        if os.path.exists(result):
            shutil.rmtree(result)

        if not os.path.exists(result):
            os.makedirs(result)

        return result


def process(path_to_book, output_path):
    try:
        target = WWResult(path_to_book, output_path)
        book_asin = get_or_create_book_asin(target.book_path)
        glosses = get_glosses(target.book_path)
    except:
        return

    if len(glosses) == 0:
        print("[.] There are no suitable words in the book")
        return

    print("[.] Count of words: {}".format(len(glosses)))

    sdr_dir_name = "{}.sdr".format(target.book_name)
    sdr_dir_path = os.path.join(target.result_dir_path, sdr_dir_name)
    if not os.path.exists(sdr_dir_path):
        os.makedirs(sdr_dir_path)

    lang_layer_db = LanguageLayerDB(sdr_dir_path, book_asin)

    path_to_script = os.path.dirname(os.path.realpath(__file__))
    path_to_nltk_data = os.path.join(path_to_script, "nltk_data")
    word_processor = WordProcessor(path_to_nltk_data)

    exp_dict = get_explanatory_dictionary()

    prfx = "[.] Processing words: "
    print_progress(0, len(glosses), prefix=prfx, suffix='')
    lang_layer_db.start_transaction()

    wlog = get_logger_for_words()
    for i, gloss in enumerate(glosses):
        wlog.debug("Gloss: {}".format(gloss))

        gloss.word = word_processor.normalize_word(gloss.word)
        if gloss.word in exp_dict:
            sense_id, difficulty = exp_dict[gloss.word]
            wlog.debug("{} - {} - {}".format(gloss.offset, gloss.word, sense_id))
            lang_layer_db.add_gloss(gloss.offset, difficulty, sense_id)

        print_progress(i + 1, len(glosses), prefix=prfx, suffix='')

    lang_layer_db.end_transaction()
    lang_layer_db.close_db()

    print("[.] Success!")
    print("Now copy this folder: \"{}\" to your Kindle".format(target.result_dir_path))


def main():
    if len(sys.argv) < 2:
        return usage()

    path_to_book = os.path.abspath(sys.argv[1])
    output_path = "."

    print("[.] Checking dependenices")
    try:
        check_dependencies()
    except ValueError as e:
        print("  [-] Checking failed:")
        print("    |", e)
        return

    process(path_to_book, output_path)


if __name__ == "__main__":
    main()
