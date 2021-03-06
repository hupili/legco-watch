#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Document wrappers for LegCo Agendas
"""

from collections import OrderedDict
import logging
import lxml
import lxml.html
from lxml import etree
from lxml.html.clean import clean_html, Cleaner
import re
from lxml.html import HTMLParser
import itertools
from raw.utils import to_string, to_unicode, grouper


logger = logging.getLogger('legcowatch-docs')
SECOND_READING_PATTERN_C = u'二讀'

BILL_AMENDMENT_PATTERN_C = u'全體委員會審議階段修正案'

FIRST_READING_PATTERN_C = u'首讀'

COMMITTEE_STAGE_PATTERN_C = u'全體委員會審議階段'

QUESTION_PATTERN_E = ur'^\*?([0-9]+)\..*?Hon\s(.*?)\sto ask:'
QUESTION_PATTERN_C = ur'^\*?([0-9]+)\.\s*(.*?)議員問:'
# Note: The first (urgent) question on 2014.11.20 does not have a number at start, causing processor to fail.
# This is a bug which occurs when a single urgent question presents, and messes up question index following.
# Since this seldom occurs, we may consider fixing or overriding those particular entries.

LEGISLATION_E = u'Subsidiary Legislation'
LEGISLATION_C = u'附屬法例'
OTHER_PAPERS_E = u'Other Paper'
OTHER_PAPERS_C = u'其他文件'
PRESENTER_E = ur'presented by (?:the )?(.+?)\)'
PRESENTER_C = ur'由(\w+?)提交'
BILL_PATTERN_C = u'條例草案'


class CouncilAgenda(object):
    """
    Object representing the Council Agenda document.  This class
    parses the document source and makes all of the individual elements easily accessible
    """
    SECTION_MAP = OrderedDict(
        (
            ('tabled_papers', [u'Tabling of Paper', u'提交文件']),
            ('members_bills', [u"Members' Bill", u"Member's Bill", u'議員法案']),
            ('members_motions', [u"Members' Motion", u"Member's Motion", u'議員議案']),
            ('questions', [u'Question', u'質詢']),
            ('bills', [u'Bill', u'法案']),
            ('motions', [u'Motion', u'議案']),
        )
    )

    def __init__(self, uid, source, *args, **kwargs):
        logger.debug(u'** Parsing agenda {}'.format(uid))
        self.uid = uid
        if uid[-1] == 'e':
            self.english = True
        else:
            self.english = False
        # Raw html string
        self.source = source
        self.tree = None
        self.tabled_papers = None
        self.questions = None
        self.question_map = None
        self.motions = None
        self.bills = None
        self.members_bills = None
        self.members_motions = None
        self.other = None
        self._headers = []
        self._load()
        self._clean()
        self._parse()

    def __repr__(self):
        return u'<CouncilAgenda: {}>'.format(self.uid)

    def _load(self):
        """
        Load the ElementTree from the source
        """
        # Convert directional quotation marks to regular quotes
        double_quotes = ur'[\u201c\u201d]'
        self.source = re.sub(double_quotes, u'"', self.source)
        single_quotes = ur'[\u2019\u2018]'
        self.source = re.sub(single_quotes, u"'", self.source)
        # Convert colons
        self.source = self.source.replace(u'\uff1a', u':')
        # Remove line breaks and tabs
        self.source = self.source.replace(u'\n', u'')
        self.source = self.source.replace(u'\t', u'')
        # There are also some "zero width joiners" in random places in the text
        # Should remove them here, since they make string search unreliable
        # these are the codes: &#8205, &#160 (nbsp), \xa0 (nbsp), \u200d
        zero_width_joiners = u'\u200d'
        self.source = self.source.replace(zero_width_joiners, u'')
        # Also previously had some non breaking spaces in unicode \u00a0, but this
        # may have been fixed by changing the parser below

        # Use the lxml cleaner
        cleaner = Cleaner()
        parser = HTMLParser(encoding='utf-8')
        # Finally, load the cleaned string to an ElementTree
        self.tree = cleaner.clean_html(lxml.html.fromstring(to_string(self.source), parser=parser))
        # self.tree = lxml.html.fromstring(to_string(self.source))

    def _clean(self):
        """
        Removes some of extraneous tags to make parsing easier
        """
        etree.strip_tags(self.tree, 'strong')
        for xx in self.tree.find_class('pydocx-tab'):
            xx.drop_tag()

    def _parse(self):
        """
        Parse the source document and populate this object's properties
        """
        # The A is for special question sections, such as the agenda on June 18, 2014
        pattern = ur'^[IVA]+\.'
        current_section = None
        # Iterate over the top level elements under body.
        # In newer documents, this is contained in a div, but otherwise divs are not present
        elems = self.tree.xpath('.//body/div/*')
        if len(elems) == 0:
            # If no div, get the direct children of body
            elems = self.tree.xpath('.//body/*')
        for elem in elems:
            # When we encounter a header element, figure out what section it is a header for
            text = elem.text_content().strip()
            if text == u'':
                continue
            if text and re.search(pattern, text):
                section_name = self._identify_section(text)
                if section_name is not None:
                    logger.debug(u'Identified header {} as {}'.format(text, section_name))
                    current_section = section_name
                else:
                    logger.warn(u"Could not identify section from header {}".format(text))
                    current_section = "other"
                # If this is the first time in this section, initailize the array for storing stuff
                if getattr(self, current_section) is None:
                    setattr(self, current_section, [])
                self._headers.append((current_section, elem))
            else:
                # Add all the elements we encounter to the list for the current section until
                # we encounter another header element, or the end of the document
                if current_section is not None:
                    arr = getattr(self, current_section)
                    arr.append(elem)

        # Once all of the sections are split up, parse each of them separately
        for section in CouncilAgenda.SECTION_MAP.keys():
            if getattr(self, section) is not None:
                getattr(self, "_parse_{}".format(section))()
        # We won't parse others, since we don't know what those are

    def _parse_tabled_papers(self):
        """
        Parse elements for tabled papers
        """
        if self.tabled_papers is None:
            return
        # Filter out paragraphs, which are actually children of the table elements
        # Actually we only want to filter out paragraphs that are children of table cell elements
        # Since some older documents don't use tables for the list of legislation (particularly other papers)
        # self.tabled_papers = [xx for xx in self.tabled_papers if xx.tag == u'table']
        logger.debug(u'Parsing tabled papers from {} elements'.format(len(self.tabled_papers)))
        legislation_header = LEGISLATION_E if self.english else LEGISLATION_C
        other_papers_header = OTHER_PAPERS_E if self.english else OTHER_PAPERS_C
        parsed_papers = []
        # For non-table elements
        paper_parts = []
        for elem in self.tabled_papers:
            # We care about two sections:
            # 1) "Subsidiary Legislation / Instruments
            # 2) "Other Paper"
            # Sometimes these are in tables, other times they are series of
            # <p> tags (usually the case in older documents)
            # Sometimes the tables are not headered, so we have to try to infer whether they
            # are subsidiary legislation or other papers
            if elem.tag == u'table':
                first_row_text = elem[0].text_content().strip()
                if first_row_text.startswith(legislation_header):
                    # Subsidiary legislation
                    # Papers occur in single rows
                    logger.debug(u'Found subsidiary legislation table')
                    # In older files, sometimes the table has all the elements after it in its iterator,
                    # so to avoid processing to much, just process the direct tr children
                    parsed_papers.append(self._parse_tabled_legislation(elem.xpath('./tr')[1:]))
                elif other_papers_header in first_row_text:
                    # Other papers table
                    # rows occur in pairs, with the first row being the title
                    # and the second row being the presenter
                    logger.debug(u'Found other papers table')
                    parsed_papers.append(self._parse_other_papers(elem.xpath('./tr')[1:]))
                else:
                    # No title, try to infer the table
                    # For some Chinese agendas, it seems like the title is not included
                    # or it could be in a different element
                    # Check the second row to see if there are parenthesis
                    # If there are, then it's likely Other papers
                    # Or, can check the last column to see if there is a legislation number
                    paper_number = ur'^\d+/\d+$'
                    last_col = elem[0][-1].text_content().strip()
                    match = re.search(paper_number, last_col)
                    if match:
                        logger.debug(u'Inferred subsidiary legislation table')
                        parsed_papers.append(self._parse_tabled_legislation(elem.xpath('./tr')))
                    else:
                        logger.debug(u'Inferred other papers table')
                        parsed_papers.append(self._parse_other_papers(elem.xpath('./tr')))
            else:
                # If it's not a table, then it's probably a list of other papers
                # in a Chinese agenda.  We need to consume these elements sequentially
                # and look for the presenter as a delimiter
                text = elem.text_content().strip()
                if text.startswith(other_papers_header) or text.startswith(legislation_header):
                    continue
                match_pattern = PRESENTER_E if self.english else PRESENTER_C
                match = re.search(match_pattern, text, re.UNICODE)
                if match:
                    # Found the presenter statement, signifying the end of the paper
                    paper_parts.append(elem)
                    parsed_papers.append([OtherTabledPaper(paper_parts, self.english)])
                    paper_parts = []
                else:
                    paper_parts.append(elem)
        self.tabled_papers = list(itertools.chain.from_iterable(parsed_papers))

    def _parse_tabled_legislation(self, tbl):
        parsed_papers = []
        for item in tbl:
            # Sometimes there are blank rows
            if item.text_content().strip() == u'':
                continue
            try:
                parsed = TabledLegislation(item, self.english)
                logger.debug(u'Found legislation {}'.format(parsed.title))
                parsed_papers.append(parsed)
            except IndexError:
                logger.warning(u'Could not parsed tabled legislation for agenda {}'.format(self.uid))
        return parsed_papers

    def _parse_other_papers(self, tbl):
        # Strip out empty rows
        tbl = [xx for xx in tbl if xx.text_content().strip() != '']
        parsed_papers = []
        grouped_tbl = grouper(tbl, 2)
        for item in grouped_tbl:
            # In this case, item is tuple of tr elements
            parsed = OtherTabledPaper(item, self.english)
            logger.debug(u'Found other paper {}'.format(parsed.title))
            parsed_papers.append(parsed)
        return parsed_papers

    def _parse_members_bills(self):
        pass

    def _parse_members_motions(self):
        pass

    def _parse_questions(self):
        """
        Parse question lxml elements into AgendaQuestions.

        When this is run, self.questions is a list of lxml elements.  This will
        scan through the list, and give groups of elements that constitute a question
        to the AgendaQuestion constructor.
        """
        if self.questions is None:
            return

        logger.debug(u"Parsing questions from {} elements".format(len(self.questions)))
        parsed_questions = []
        pattern = QUESTION_PATTERN_E if self.english else QUESTION_PATTERN_C
        parts = []
        for q in self.questions:
            content = q.text_content().strip()
            # Discard empty elements
            if content == '':
                continue
            # Match for question starts
            match = re.match(pattern, content)
            if match is not None:
                # Found a match for a new question start
                # If we've accumulated parts for a prior question, clear those out
                if len(parts) > 0:
                    ag = AgendaQuestion(parts, english=self.english)
                    parsed_questions.append(ag)
                    parts = []
                logger.debug(u"Found question {}".format(content))
            # Continue to accumulate parts
            parts.append(q)

        # Make sure to parse the last question
        ag = AgendaQuestion(parts, english=self.english)
        parsed_questions.append(ag)
        self.questions = parsed_questions
        logger.debug(u"Parsed {} questions".format(len(self.questions)))
        self._build_question_map()

    def _build_question_map(self):
        # Map the question numbers to question objects.
        # Since sometimes we may get urgent questions that have their own numbering system,
        # the value in the map maybe a list
        self.question_map = {}
        for question in self.questions:
            if question.number not in self.question_map:
                self.question_map[question.number] = question
            else:
                val = self.question_map[question.number]
                if isinstance(val, list):
                    val.append(question)
                else:
                    self.question_map[question.number] = [val, question]

    def _parse_bills(self):
        """

        from raw.docs.agenda import get_all_agendas, CouncilAgenda
        from raw.models import RawCouncilAgenda
        from raw import utils
        import itertools
        import random

        agendas = get_all_agendas(1)
        objs = []
        sample = [xx.get_parser() for xx in random.sample(agendas[0:100], 50)]
        sample = [xx for xx in sample if xx.bills is not None]

        # Seems like most bills in english agendas are in tables, and the first row is the stage that the bill is in
        # Try to get an inventory of all the possible bill headers
        bills = itertools.chain.from_iterable([xx.bills for xx in sample])
        bill_tables = [xx for xx in bills if xx.tag == 'table']
        bill_headers = set([xx[0].text_content().strip() for xx in bill_tables])

        # main headers appear to be:
        # First Reading
        # Second Reading (debate to resume)
        # Second Reading (debate to resume), Committee Stage and Third Reading
        # Second Reading (debate to be adjourned)
        # Committee Stage and Third Reading

        # But lots of noise

        # Strategy is to iterate over the table elements in the bills list
        # If we find that the header of the table includes one of the first, second, or third readings, then we
        # pass to a method ot handle that kind of a table
        # First reading bills only have title, no government official
        # Second and third reading bills have a government official column present
        # Committee stage bills have possible amendments in rows under the bill

        """

        if self.bills is None:
            return
        if self.english:
            self._parse_english_bills()
        else:
            self._parse_chinese_bills()

    def _parse_chinese_bills(self):
        logger.debug(u"Parsing bills from {} elements".format(len(self.bills)))
        parsed_bills = []
        for i in range(len(self.bills)):
            # For chinese bills, the headers are outside of the tables and enclosed in <p> tags.
            # So check if the the tag is a p tag, and if it matches a header text
            this_element = self.bills[i]
            # Hack check for IndexError, probably from malformed document
            if this_element.tag == 'p' and i+1 < len(self.bills):
                text = this_element.text_content().strip()
                if text.startswith(FIRST_READING_PATTERN_C):
                    logger.debug(u'Found first reading bills table headered: {}'.format(text))
                    # First reading
                    table = self.bills[i+1]
                    for row in table.xpath('./tr'):
                        title = row[-1].text_content().strip()
                        bill = BillReading(title, BillReading.FIRST)
                        parsed_bills.append(bill)
                elif COMMITTEE_STAGE_PATTERN_C in text:
                    # Second and committee stage
                    logger.debug(u'Found committee stage bills table headered: {}'.format(text))
                    if text.startswith(COMMITTEE_STAGE_PATTERN_C):
                        stage = BillReading.THIRD
                    else:
                        stage = BillReading.SECOND_THIRD
                    table = self.bills[i+1]
                    rows = table.xpath('./tr')
                    attendees = []
                    amendments = []
                    r = 0
                    max_r = len(rows)
                    next_r = 1
                    title = None
                    while r < max_r:
                        this_row = rows[r]
                        row_text = this_row.text_content().strip()
                        # Check for amendments first
                        if BILL_AMENDMENT_PATTERN_C in row_text:
                            amendments.append(this_row[-1].text_content().strip())
                        elif BILL_PATTERN_C not in row_text:
                            # More attendees
                            attendees.append(this_row[-1].text_content().strip())
                        else:
                            # If this isn't the first row, close the prior bill
                            if r > 0 and title is not None:
                                bill = BillReading(title, stage, attendees, amendments)
                                parsed_bills.append(bill)
                                attendees = []
                                amendments = []
                            # An actual bill
                            # We go from the right, since sometimes there are numbers as the first column
                            title = this_row[-3].text_content().strip()
                            attendees.append(this_row[-1].text_content().strip())
                        r = next_r
                        next_r += 1
                    # Close the last bill
                    bill = BillReading(title, stage, attendees, amendments)
                    parsed_bills.append(bill)
                elif text.startswith(SECOND_READING_PATTERN_C):
                    logger.debug(u'Found second reading bills table headered: {}'.format(text))
                    rows = self.bills[i+1].xpath('./tr')
                    for row in rows:
                        title = row[-3].text_content().strip()
                        attendees = [row[-1].text_content().strip()]
                        bill = BillReading(title, BillReading.SECOND, attendees)
                        parsed_bills.append(bill)
                else:
                    # Unknown tag
                    logger.warning(u'Unknown bills table header: {}'.format(text))

        self.bills = parsed_bills

    def _parse_english_bills(self):
        logger.debug(u"Parsing bills from {} elements".format(len(self.bills)))
        parsed_bills = []
        for b in self.bills:
            if b.tag != 'table':
                continue
            header = b[0].text_content().strip().lower()
            if header.startswith(u'first reading'):
                logger.debug(u'Found first reading bills table headered: {}'.format(header))
                for row in b.xpath('./tr')[1:]:
                    title = row[-1].text_content().strip()
                    bill = BillReading(title, BillReading.FIRST)
                    parsed_bills.append(bill)
            elif u'committee stage' in header:
                logger.debug(u'Found committee stage bills table headered: {}'.format(header))
                if header.startswith(u'committee stage'):
                    stage = BillReading.THIRD
                else:
                    stage = BillReading.SECOND_THIRD
                rows = b.xpath('./tr')[1:]
                # Need to use an index here, so we can check the following row to see if there is:
                # a continuation with more attendees, as in council_agenda-20140416-e
                # or amendments, as in council_agenda-20131218-e
                attendees = []
                amendments = []
                r = 0
                max_r = len(rows)
                next_r = 1
                title = None
                while r < max_r:
                    this_row = rows[r]
                    row_text = this_row.text_content().strip()
                    # Check for amendments first
                    if u'Committee stage amendments' in row_text:
                        amendments.append(this_row[-1].text_content().strip())
                    elif u'Bill' not in row_text:
                        # More attendees
                        attendees.append(this_row[-1].text_content().strip())
                    else:
                        # If this isn't the first row, close the prior bill
                        if r > 0 and title is not None:
                            bill = BillReading(title, stage, attendees, amendments)
                            parsed_bills.append(bill)
                            attendees = []
                            amendments = []
                        # An actual bill
                        # We go from the right, since sometimes there are numbers as the first column
                        title = this_row[-3].text_content().strip()
                        attendees.append(this_row[-1].text_content().strip())
                    r = next_r
                    next_r += 1
                # Close the last bill
                bill = BillReading(title, stage, attendees, amendments)
                parsed_bills.append(bill)
            elif header.startswith('second reading'):
                logger.debug(u'Found second reading bills table headered: {}'.format(header))
                rows = b.xpath('./tr')[1:]
                for row in rows:
                    title = row[-3].text_content().strip()
                    attendees = [row[-1].text_content().strip()]
                    bill = BillReading(title, BillReading.SECOND, attendees)
                    parsed_bills.append(bill)
            else:
                # Unknown tag
                logger.warning(u'Unknown bills table header: {}'.format(header))
        self.bills = parsed_bills

    def _parse_motions(self):
        pass

    def _identify_section(self, header):
        """
        Try to identify what section the header delineates
        Returns None if it can't identify the section, otherwise it returns the property
        """
        # Need to keep order of the map because we need to check for members' bills before
        # we check for bills
        for prop_name, check_strings in CouncilAgenda.SECTION_MAP.items():
            if any_in(check_strings, header):
                return prop_name
        return None

    def get_headers(self):
        """
        Gets the headers from the document
        """
        text = self.tree.xpath('//text()')
        pattern = ur'^[IV]+\.'
        res = []
        for p in text:
            if re.search(pattern, p):
                res.append(p)
        return res


class AgendaQuestion(object):
    """
    Object for questions listed in the CouncilAgenda

    Instantiate with the list of lxml elements that comprise
    the question, and this object will parse out the sections
    """
    RESPONDER_PATTERN = ur':\s?(.+)$'
    QTYPE_ORAL = 1
    QTYPE_WRITTEN = 2

    def __init__(self, elements, english=True):
        self._elements = elements

        # Get the asker
        text = elements[0].text_content().strip()
        pattern = QUESTION_PATTERN_E if english else QUESTION_PATTERN_C
        match = re.match(pattern, text)
        if match is not None:
            self.number = match.group(1)
            self.asker = match.group(2)
            # Get question type
            # Can be oral or written.  Could also be urgent, in this case the heading can be 
            # "根據《議事規則》第24(4)條提出的質詢 " - but no discrimination is made yet
            if text.startswith('*'):
                self.type = self.QTYPE_WRITTEN
            else:
                self.type = self.QTYPE_ORAL
        else:
            logger.warn(u'Could not find asker of question in element: {}'.format(text))
            self.number = None
            self.asker = None
            self.type = None

        # Get the responder
        # If the question is the last question, then there may be a note
        # that begins with an asterisk that says which questions were
        # for written reply
        # As a heuristic, just search the last two elements, and keep track
        # of which is the last index of the body of the question

        # In other cases, if there is more than one public officer to reply, then
        # the list of public officers could be split across two elements.  See, for example,
        # the agenda from June 18, 2014, question 1
        ending_index = -2
        for e in elements[-2:]:
            text = e.text_content().strip()
            match = re.search(AgendaQuestion.RESPONDER_PATTERN, text)
            if match is not None:
                self.replier = match.group(1)
                break
            ending_index += 1
        else:
            logger.warn(u'Could not find responder of question in element: {}'.format(text))
            self.replier = None

        # Store the rest of the elements into the body as html
        self.body = ''.join([etree.tounicode(xx, method='html') for xx in elements[1:ending_index]])

    def __repr__(self):
        return u'<Question by {}>'.format(self.asker).encode('utf-8')


class TabledLegislation(object):
    """
    Object for tabled subsidiary legislation and instruments.  These will
    typically have a canonical title and a legislation number

    Instantiated with a tr element that is a row in the table of subsidiary legislation
    """
    def __init__(self, row, english=True):
        # Sometimes the first column is a number, other times the number is not present
        # So we start from the last column, since that should always be the paper number
        self.number = row[-1].text_content().strip()
        # Sometimes there is a blank column in between the paper number and the title
        title = row[-2].text_content().strip()
        if title == '':
            self.title = row[-3].text_content().strip()
        else:
            self.title = title

    def __repr__(self):
        return u'<TabledLegislation {}: {}>'.format(self.number, self.title).encode('utf-8')


class OtherTabledPaper(object):
    """
    Other tabled papers

    Instantiated with a tuple of two tr elements, or a list of p elements
    """
    def __init__(self, rows, english=True):
        self.presenter = None
        join_string = u' ' if english else u''
        if rows[0].tag == 'tr':
            # The HTML uses things like BRs and spans to split the text up, but these
            # are removed by text_content().  So we'll need to add a space for each element,
            # then convert duplicate spaces to a single space
            if english:
                title_elems = rows[0].xpath('.//*')
                for e in title_elems:
                    e.tail = u' ' + e.tail if e.tail else u' '
            title = rows[0].text_content().strip()
            # Strip out any starting numbers
            title = re.sub(ur'^\d+.[ ]?', u'', title)
            self.title = join_string.join(title.split())
            if rows[1] is not None:
                match_pattern = PRESENTER_E if english else PRESENTER_C
                text = rows[1].text_content().strip()
                match = re.search(match_pattern, text, re.UNICODE)
                if match is not None:
                    self.presenter = match.group(1)
        else:
            # series of p elements.  Last element is the presenter
            match_pattern = PRESENTER_E if english else PRESENTER_C
            text = rows[-1].text_content().strip()
            match = re.search(match_pattern, text, re.UNICODE)
            if match is not None:
                self.presenter = match.group(1)
            title = join_string.join([xx.text_content().strip() for xx in rows[0:-1]])
            title = re.sub(ur'^\d+.[ ]?', '', title)
            self.title = title


    def __repr__(self):
        return u'<OtherTabledPaper {}>'.format(self.title).encode('utf-8')


class BillReading(object):
    FIRST = 1
    SECOND = 2
    SECOND_THIRD = 23
    THIRD = 3
    READING_TEXT = {
        FIRST: u'First reading',
        SECOND: u'Second reading',
        SECOND_THIRD: u'Second reading, committee stage and third reading',
        THIRD: u'Committee stage and third reading'
    }

    def __init__(self, title, reading, attendees=None, amendments=None):
        self.title = title
        self.attendees = attendees if attendees is not None else []
        self.amendments = amendments if amendments is not None else []
        self.reading = reading
        logger.debug(u'Parsed bill {} at {}'.format(self.title, self.READING_TEXT[self.reading]))

    def __repr__(self):
        return to_string(u'<BillReading {} {}>'.format(self.title, self.reading))

    @property
    def pretty_reading(self):
        return self.READING_TEXT[self.reading]


class AgendaMotion(object):
    """
    Object for Members' Motions.
    """
    def __init__(self, elements):
        self.mover = None
        self.body = None
        self.amendments = None


class MotionAmendment(object):
    """
    Amendments to motions.
    """
    def __init__(self, parent, elements):
        self.motion = parent
        self.amender = None
        self.body = None


def any_in(arr, iterable):
    """
    Checks if any value in arr is in an iterable
    """
    for elem in arr:
        if elem in iterable:
            return True
    return False


def get_all_agendas(language=0):
    from raw import models
    objs = models.RawCouncilAgenda.objects.order_by('-uid')
    if language == 1:
        objs = objs.filter(language=models.LANG_CN)
    if language == 2:
        objs = objs.filter(language=models.LANG_EN)
    return objs.all()


"""

# Try to figure out all of the strings that we need to account for
import logging
from raw.docs.agenda import get_all_agendas, CouncilAgenda
from raw import utils
agendas = get_all_agendas()
headers = []
for ag in agendas:
    logging.debug(ag)
    if ag[1] == "DOCX":
        src = utils.docx_to_html(ag[2])
    elif ag[1] == "DOC":
        src = utils.doc_to_html(ag[2])
    else:
        continue
    res = CouncilAgenda(ag[0].uid, src)
    headers.append(res.get_headers())
import itertools
import re
pattern = ur'^[IV]+\.\s?'
flat_headers = list(itertools.chain.from_iterable(headers))
flat_headers = [re.sub(pattern, u'', xx) for xx in flat_headers]
unique_headers = set(flat_headers)
unique_headers = sorted(list(unique_headers))
# there are some headers that get the roman numerals, but miss the title, possibly because of some
# wayward tag

Address by the Chief Executive
Addresses
Bill
Bills
Election of President
Member's Bill
Member's Motion
Members' Bills
Members' Motion
Members' Motions
Members' Motions on Subsidiary Legislation and Other Instruments
Motion
Motions
Question under Rule 24(4) of the Rules of Procedure
Questions
Questions for Written Replies
Questions under Rule 24(4) of the Rules of Procedure
Special Motions
Statements
Tabling of Paper
Tabling of Papers
Taking of Legislative Council Oath
The Chief Executive of the Hong Kong Special Administrative Region   presents the Policy Address
The Chief Executive of the Hong Kong Special Administrative Region  presents the Policy Address
The Chief Executive of the Hong Kong Special Administrative Region  presents the Policy Address to the Council
The Chief Executive's Question and Answer Session
 Motions
以書面答覆的質詢
作出立法會誓言
提交文件
根據《議事規則》第24(4)條提出的質詢
法案
發言
聲明
行政長官發言
行政長官答問會
議員就附屬法例及其他文書提出的議案
議員法案
議員議案
議案
質詢
選舉主席
香港特別行政區行政長官向本會發表施政報告
香港特別行政區行政長官發表施政報告


from raw.docs.agenda import get_all_agendas, CouncilAgenda
from raw.models import RawCouncilAgenda
from raw import utils
import random

agendas = get_all_agendas()
objs = []
sample = [xx.get_parser() for xx in random.sample(agendas[0:100], 10)]

tbls = []
for xx in sample:
    tbls.append([xxx for xxx in xx.tabled_papers if xxx.tag == 'table'])
"""


