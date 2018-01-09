# encoding: utf-8

"""A Glyphs plugin to automatically place LSB/RSB/TSB/BSB anchors according to palt/vpal values when opening a font."""

import objc
from GlyphsApp import *
from GlyphsApp.plugins import *

import os
import contextlib
import collections
from fontTools.ttLib import TTFont
from Foundation import NSBundle

class CJKAnchorImportPlugin(GeneralPlugin):
    
    def start(self):
        Glyphs.addCallback(self.documentOpened, DOCUMENTOPENED)
    
    def documentOpened(self, notification):
        document = notification.object()
        font = document.font
        if font.filepath and os.path.splitext(font.filepath)[1].lower() in ['.otf', '.ttf', '.otc', '.ttc']:
            self.__import_anchors(font)
    
    def __import_anchors(self, font):
        with GSFontUpdatingContext(font):
            reader = CJKAlternateMetricsGPOSReader(TTFont(font.filepath))
            if reader.has_metrics:
                cid_rename_dict = self.__make_cid_rename_dict(font, dest='cid')
                for glyph in font.glyphs:
                    for master in font.masters:
                        layer = glyph.layers[master.id]
                        edge_insets = reader.edge_insets.get(glyph.name)
                        if not edge_insets and cid_rename_dict and glyph.name in cid_rename_dict:
                            edge_insets = reader.edge_insets.get(cid_rename_dict[glyph.name])
                        if edge_insets:
                            center = NSPoint(layer.width / 2.0, font.upm / 2.0 + master.descender)
                            self.__clear_anchors(layer, ('LSB', 'RSB', 'TSB', 'BSB'))
                            if edge_insets.left != 0:
                                self.__upsert_anchor(layer, 'LSB', NSPoint(edge_insets.left,  center.y))
                            if edge_insets.right != 0:    
                                self.__upsert_anchor(layer, 'RSB', NSPoint(layer.width - edge_insets.right, center.y))
                            if edge_insets.top != 0:
                                self.__upsert_anchor(layer, 'TSB', NSPoint(center.x, font.upm - edge_insets.top + master.descender))
                            if edge_insets.bottom != 0:
                                self.__upsert_anchor(layer, 'BSB', NSPoint(center.x, edge_insets.bottom + master.descender))
                        else:
                            self.__clear_anchors(layer, ('LSB', 'RSB', 'TSB', 'BSB'))
        
    def __clear_anchors(self, layer, names):
        for name in names:
            layer.removeAnchorWithName_(name)
    
    def __upsert_anchor(self, layer, name, position):
        if name in layer.anchors:
            layer.anchors[name].position = position
        else:
            layer.anchors.append(GSAnchor(name, position))

    def __make_cid_rename_dict(self, font, dest='cid'):
        operation = objc.lookUpClass('GSExportInstanceOperation').alloc().initWithFont_instance_format_(Glyphs.font, None, 0)
        ros      = operation.CIDRescoureName()
        ro       = operation.CIDShortRescoureName()
        if ros and ro:
            filename = NSBundle.bundleWithPath_(os.path.join(NSBundle.mainBundle().builtInPlugInsPath(), 'OTF.glyphsFileFormat')).pathForResource_ofType_('MapFile{0}'.format(ro), 'txt')
            if filename:
                with open(filename, 'r') as file:
                    make_tuple = (lambda c: (c[1], 'cid{0:05d}'.format(int(c[0])))) if dest == 'cid' else (lambda c: ('cid{0:05d}'.format(int(c[0])), c[1]))
                    rename_dict = dict([make_tuple(line.split('\t')) for line in file])
                    return rename_dict
        return None
    
    def __file__(self):
        """Please leave this method unchanged"""
        return __file__


@contextlib.contextmanager
def GSFontUpdatingContext(font):
    font.disableUpdateInterface()
    try:
        yield font
    finally:
        font.enableUpdateInterface()


H = 0
V = 1
Adjustment = collections.namedtuple('Adjustment', ['glyph', 'placement', 'advance', 'direction'])
EdgeInsets = collections.namedtuple('EdgeInsets', ['left', 'right', 'top', 'bottom'])

class CJKAlternateMetricsGPOSReader(object):
    
    def __init__(self, font):
        self.__font = font
        self.__setup(font)
    
    # - preparing lists and dictionaries
    
    def __setup(self, font):
        table = font['GPOS'].table
        self.__table = table
        self.__tag_list = self.__make_tag_list(table)
        self.__tag_lookup_dict = self.__make_tag_lookup_dict(table)
        self.__lookup_adjustments_dict = self.__make_lookup_adjustments_dict(table)
        self.__edge_insets_dict = self.__make_edge_insets_dict()
    
    def __make_tag_list(self, table):
        l = [r.FeatureTag for r in table.FeatureList.FeatureRecord]
        s = set(l)
        return [tag for tag in sorted(s, key=lambda x: l.index(x))]
        
    def __make_tag_lookup_dict(self, table):
        d = {}
        for record in table.FeatureList.FeatureRecord:
            tag = record.FeatureTag
            if tag not in d:
                d[tag] = set([])    
            indices = record.Feature.LookupListIndex
            d[tag].update(indices)
        for tag in list(d.keys()):
            d[tag] = [table.LookupList.Lookup[i] for i in sorted(d[tag])]
        return d

    def __make_lookup_adjustments_dict(self, table):
        return dict([[lookup, self.__make_adjustments_from_lookup(lookup)] for lookup in table.LookupList.Lookup])
    
    def __make_edge_insets_from_adjustments(self, adjustments):
        placement_x, advance_x, placement_y, advance_y = (0, 0, 0, 0)
        for adjustment in adjustments:
            if adjustment.direction == H:
                placement_x += adjustment.placement
                advance_x   += adjustment.advance
            elif adjustment.direction == V:
                placement_y += adjustment.placement
                advance_y   += adjustment.advance
        return EdgeInsets(-placement_x, -(advance_x - placement_x), placement_y, -(advance_y + placement_y))
        
    def __make_edge_insets_dict(self):
        d = {}
        for tag in self.tags:
            if tag in ('palt', 'vpal'):
                for adjustment in self.adjustments_from_tag(tag):
                    if adjustment.glyph not in d:
                        d[adjustment.glyph] = []
                    d[adjustment.glyph].append(adjustment)
        for glyph in list(d.keys()):
            d[glyph] = self.__make_edge_insets_from_adjustments(d[glyph])
        return d
    
    # - public methods
    
    @property
    def font(self):
        return self.__font
    
    @property
    def tags(self):
        return tuple(self.__tag_list)
    
    @property
    def has_metrics(self):
        return 'palt' in self.tags or 'vpal' in self.tags
    
    @property
    def edge_insets(self):
        return self.__edge_insets_dict
    
    def lookups_from_tag(self, tag):
        return self.__tag_lookup_dict.get(tag, [])
    
    def adjustments_from_lookup(self, lookup):
        return self.__lookup_adjustments_dict.get(lookup, [])
    
    def adjustments_from_tag(self, tag):
        return sum([self.adjustments_from_lookup(lookup) for lookup in self.lookups_from_tag(tag)], [])
    
    # - lookup parsing
    
    def __make_adjustments_from_lookup(self, lookup):
        adjustments = []
        if lookup.LookupType == 1:
            for subtable in lookup.SubTable:
                adjustments.extend(self.__make_adjustments_from_subtable(subtable))
        return adjustments

    def __make_adjustment_from_value_in_format_1(self, glyph, value):
        return Adjustment(glyph, value.XPlacement, 0, H)
        
    def __make_adjustment_from_value_in_format_2(self, glyph, value):
        return Adjustment(glyph, value.YPlacement, 0, V)
        
    def __make_adjustment_from_value_in_format_4(self, glyph, value):
        return Adjustment(glyph, 0, value.XAdvance, H)
    
    def __make_adjustment_from_value_in_format_5(self, glyph, value):
        return Adjustment(glyph, value.XPlacement, value.XAdvance, H)
    
    def __make_adjustment_from_value_in_format_8(self, glyph, value):
        return Adjustment(glyph, 0, value.YAdvance, V)
        
    def __make_adjustment_from_value_in_format_10(self, glyph, value):
        return Adjustment(glyph, value.YPlacement, value.YAdvance, V)
    
    def __make_adjustments_from_subtable(self, subtable):
        adjustments = []
        if subtable.Format == 2:
            make_adjustment_from_value = {
                1:  self.__make_adjustment_from_value_in_format_1,
                2:  self.__make_adjustment_from_value_in_format_2,
                4:  self.__make_adjustment_from_value_in_format_4,
                5:  self.__make_adjustment_from_value_in_format_5,
                8:  self.__make_adjustment_from_value_in_format_8,
                10: self.__make_adjustment_from_value_in_format_10,
            }.get(subtable.ValueFormat)
            if make_adjustment_from_value:
                glyphs = [str(glyph) for glyph in subtable.Coverage.glyphs]
                for i, value in enumerate(subtable.Value):
                    adjustments.append(make_adjustment_from_value(glyphs[i], value))
        return adjustments
    
    # - 
    
    @staticmethod
    def test_drive_with_font_at_path(path):
        from pprint import pprint
        
        font = TTFont(path)
        reader = CJKAlternateMetricsGPOSReader(font)
        
        # dump tables
        for tag in reader.tags:
            print('{0}:'.format(tag))
            for adjustment in reader.adjustments_from_tag(tag):
                print('    {0}'.format(str(adjustment)))
        
        # prettification
        pprint(reader.edge_insets)
