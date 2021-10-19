# Output backends for sigmac 
# Copyright 2021 HAWK.io

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.



import re
import sigma
import json
import uuid
from sigma.parser.modifiers.base import SigmaTypeModifier
from sigma.parser.modifiers.type import SigmaRegularExpressionModifier
from .base import SingleTextQueryBackend
from .mixins import MultiRuleOutputMixin


class HAWKBackend(SingleTextQueryBackend):
    """Converts Sigma rule into HAWK search"""
    identifier = "hawk"
    active = True
    config_required = False
    default_config = ["sysmon", "hawk"]
    reEscape = re.compile('(")')
    logname = None
    reClear = None
    andToken = " , "
    orToken = " , "
    subExpression = "{\"id\": \"and\", \"key\": \"And\", \"children\": [%s] }"
    listExpression = "%s"
    listSeparator = " "
    valueExpression = "%s"
    keyExpression = "%s"
    nullExpression = "%s = null"
    notNullExpression = "%s != null"
    mapExpression = "%s=%s"
    mapListsSpecialHandling = True
    aql_database = "events"

    def cleanKey(self, key):
        if key == None:
            return ""
        return self.sigmaparser.config.get_fieldmapping(key).resolve_fieldname(key, self.sigmaparser)

    def cleanValue(self, value):
        """Remove quotes in text"""
        # return value.replace("\'","\\\'")
        return value

    def generateNode(self, node, notNode=False):
        #print(type(node))
        #print(node)
        if type(node) == sigma.parser.condition.ConditionAND:
            return self.generateANDNode(node)
        elif type(node) == sigma.parser.condition.ConditionOR:
            #print("OR NODE")
            #print(node)
            return self.generateORNode(node)
        elif type(node) == sigma.parser.condition.ConditionNOT:
            #print("NOT NODE")
            #print(node)
            return self.generateNOTNode(node)
        elif type(node) == sigma.parser.condition.ConditionNULLValue:
            return self.generateNULLValueNode(node)
        elif type(node) == sigma.parser.condition.ConditionNotNULLValue:
            return self.generateNotNULLValueNode(node)
        elif type(node) == sigma.parser.condition.NodeSubexpression:
            #print(node)
            return self.generateSubexpressionNode(node)
        elif type(node) == tuple:
            #print("TUPLE: ", node)
            return self.generateMapItemNode(node, notNode)
        elif type(node) in (str, int):
            nodeRet = {"key": "",  "description": "", "class": "column", "return": "str", "args": { "comparison": { "value": "regex" }, "str": { "value": "5" } } }
            #key = next(iter(self.sigmaparser.parsedyaml['detection'])) 
            key = "payload"

            #nodeRet['key'] = self.cleanKey(key).lower()
            nodeRet['key'] = key

            #print(node)
            #print("KEY: ", key)
            # they imply the entire payload
            nodeRet['description'] = key
            nodeRet['rule_id'] = str(uuid.uuid4())
            nodeRet['args']['str']['value'] = self.generateValueNode(node, False)
            # return json.dumps(nodeRet)
            return nodeRet
        elif type(node) == list:
            return self.generateListNode(node, notNode)
        else:
            raise TypeError("Node type %s was not expected in Sigma parse tree" % (str(type(node))))

    def generateANDNode(self, node):
        """
        generated = [ self.generateNode(val) for val in node ]
        filtered = [ g for g in generated if g is not None ]
        if filtered:
            if self.sort_condition_lists:
                filtered = sorted(filtered)
            return self.andToken.join(filtered)
        else:
            return None
        """
        ret = { "id" : "and", "key": "And", "children" : [ ] }
        generated = [ self.generateNode(val) for val in node ]
        filtered = [ g for g in generated if g is not None ]
        if filtered:
            if self.sort_condition_lists:
                filtered = sorted(filtered)
            ret['children'] = filtered
            # return json.dumps(ret)# self.orToken.join(filtered)
            return ret
        else:
            return None

    def generateORNode(self, node):
        ret = { "id" : "or", "key": "Or", "children" : [ ] }
        generated = [ self.generateNode(val) for val in node ]
        filtered = [ g for g in generated if g is not None ]
        if filtered:
            if self.sort_condition_lists:
                filtered = sorted(filtered)
            ret['children'] = filtered
            # return json.dumps(ret)# self.orToken.join(filtered)
            return ret
        else:
            return None

    def generateSubexpressionNode(self, node):
        generated = self.generateNode(node.items)
        if 'len'in dir(node.items): # fix the "TypeError: object of type 'NodeSubexpression' has no len()"
            if len(node.items) == 1:
                # A sub expression with length 1 is not a proper sub expression, no self.subExpression required
                return generated
        if generated:
            return json.loads(self.subExpression % json.dumps(generated))
        else:
            return None

    def generateListNode(self, node, notNode=False):
        if not set([type(value) for value in node]).issubset({str, int}):
            raise TypeError("List values must be strings or numbers")
        result = [self.generateNode(value, notNode) for value in node]
        if len(result) == 1:
            # A list with length 1 is not a proper list, no self.listExpression required
            return result[0]
        #print("LIST EXPRESSION")
        #print(result)
        return self.listExpression % (self.listSeparator.join(result))

    def generateNOTNode(self, node):
        generated = self.generateNode(node.item, True)
        return generated

    def generateMapItemNode(self, node, notNode=False):
        nodeRet = {"key": "",  "description": "", "class": "column", "return": "str", "args": { "comparison": { "value": "=" }, "str": { "value": 5 } } }
        if notNode:
            nodeRet["args"]["comparison"]["value"] = "!="
        nodeRet['rule_id'] = str(uuid.uuid4())
        key, value = node
        if self.mapListsSpecialHandling == False and type(value) in (str, int, list) or self.mapListsSpecialHandling == True and type(value) in (str, int):
            nodeRet['key'] = self.cleanKey(key).lower()
            nodeRet['description'] = key
            if key.lower() in ("logname","source"):
                self.logname = value
            elif type(value) == str and "*" in value:
                # value = value.replace("*", ".*")
                value = value.replace("*", "")
                if notNode:
                    nodeRet["args"]["comparison"]["value"] = "!regex"
                else:
                    nodeRet['args']['comparison']['value'] = "regex"
                nodeRet['args']['str']['value'] = value
                # return "%s regex %s" % (self.cleanKey(key), self.generateValueNode(value, True))
                #return json.dumps(nodeRet)
                return nodeRet
            elif type(value) is str:
                #return self.mapExpression % (self.cleanKey(key), self.generateValueNode(value, True))
                nodeRet['args']['str']['value'] = value
                # return json.dumps(nodeRet)
                return nodeRet
            elif type(value) is int:
                nodeRet['return'] = "int"
                nodeRet['args']['int'] = { "value" : value }
                del nodeRet['args']['str'] 
                #return self.mapExpression % (self.cleanKey(key), self.generateValueNode(value, True))
                #return json.dumps(nodeRet)
                return nodeRet
            else:
                #return self.mapExpression % (self.cleanKey(key), self.generateNode(value))
                nodeRet['args']['str']['value'] = value
                #return json.dumps(nodeRet)
                return nodeRet
        elif type(value) == list:
            return self.generateMapItemListNode(key, value, notNode)
        elif isinstance(value, SigmaTypeModifier):
            return self.generateMapItemTypedNode(key, value)
        elif value is None:
            #return self.nullExpression % (key, )
            nodeRet['args']['str']['value'] = None
            #return json.dumps(nodeRet)
            return nodeRet
        else:
            raise TypeError("Backend does not support map values of type " + str(type(value)))

    def generateMapItemListNode(self, key, value, notNode=False):
        ret = { "id" : "or", "key": "Or", "children" : [ ] }
        for item in value:
            nodeRet = {"key": "",  "description": "", "class": "column", "return": "str", "args": { "comparison": { "value": "=" }, "str": { "value": "5" } } }
            nodeRet['key'] = self.cleanKey(key).lower()
            nodeRet['description'] = key
            nodeRet['rule_id'] = str(uuid.uuid4())
            if item is None:
                nodeRet['args']['str']['value'] = 'null'
                ret['children'].append( nodeRet )
            elif type(item) == str and "*" in item:
                item = item.replace("*", "")
                # item = item.replace("*", ".*")
                #print("item")
                #print(item)
                nodeRet['args']['str']['value'] = item # self.generateValueNode(item, True)
                if notNode:
                    nodeRet["args"]["comparison"]["value"] = "!regex"
                else:
                    nodeRet['args']['comparison']['value'] = "regex"
                ret['children'].append( nodeRet )
            else:
                #print("item2")
                #print(item)
                nodeRet['args']['str']['value'] = self.generateValueNode(item, True)
                ret['children'].append( nodeRet )
        # return json.dumps(ret) # '('+" or ".join(itemslist)+')'
        return ret # '('+" or ".join(itemslist)+')'

    def generateMapItemTypedNode(self, fieldname, value, notNode=False):
        nodeRet = {"key": "",  "description": "", "class": "column", "return": "str", "args": { "comparison": { "value": "=" }, "str": { "value": "5" } } }
        nodeRet['key'] = self.cleanKey(fieldname).lower()
        nodeRet['description'] = fieldname
        nodeRet['rule_id'] = str(uuid.uuid4())
        if type(value) == SigmaRegularExpressionModifier:
            regex = str(value)
            """
            # Regular Expressions have to match the full value in QRadar
            if not (regex.startswith('^') or regex.startswith('.*')):
                regex = '.*' + regex
            if not (regex.endswith('$') or regex.endswith('.*')):
                regex = regex + '.*'
            return "%s imatches %s" % (self.cleanKey(fieldname), self.generateValueNode(regex, True))
            """
            #print("ENDS WITH!!!")
            nodeRet['args']['str']['value'] = self.generateValueNode(regex, True)
            if notNode:
                nodeRet["args"]["comparison"]["value"] = "!regex"
            else:
                nodeRet['args']['comparison']['value'] = "regex"
            # return json.dumps(nodeRet)
            return nodeRet
        else:
            raise NotImplementedError("Type modifier '{}' is not supported by backend".format(value.identifier))

    def generateValueNode(self, node, keypresent):
        """
        if keypresent == False:
            return "payload regex \'{0}{1}{2}\'".format("%", self.cleanValue(str(node)), "%")
        else:
            return self.valueExpression % (self.cleanValue(str(node)))
        """
        return self.valueExpression % (self.cleanValue(str(node)))

    def generateNULLValueNode(self, node):
        # node.item
        nodeRet = {"key": node.item,  "description": node.item, "class": "column", "return": "str", "args": { "comparison": { "value": "=" }, "str": { "value": "null" } } }
        nodeRet['rule_id'] = str(uuid.uuid4())
        # return json.dumps(nodeRet)
        return nodeRet

    def generateNotNULLValueNode(self, node):
        # return self.notNullExpression % (node.item)
        return node.item

    def generateAggregation(self, agg, timeframe='00'):
        if agg == None:
            return ""
        if agg.aggfunc == sigma.parser.condition.SigmaAggregationParser.AGGFUNC_NEAR:
            raise NotImplementedError("The 'near' aggregation operator is not yet implemented for this backend")
        if agg.groupfield == None:
            s = "SELECT %s(%s) as agg_val from %s where" % (agg.aggfunc_notrans, self.cleanKey(agg.aggfield), self.aql_database)
            s2 = " group by %s having agg_val %s %s" % (self.cleanKey(agg.aggfield), agg.cond_op, agg.condition)
            raise NotImplementedError("The 'agg val' aggregation operator is not yet implemented for this backend: %s %s" % (s, s2))
        """
        elif agg.groupfield != None and timeframe == '00':
                self.prefixAgg = " SELECT %s(%s) as agg_val from %s where " % (agg.aggfunc_notrans, self.cleanKey(agg.aggfield), self.aql_database)
                self.suffixAgg = " group by %s having agg_val %s %s" % (self.cleanKey(agg.groupfield), agg.cond_op, agg.condition)
                return self.prefixAgg, self.suffixAgg
        elif agg.groupfield != None and timeframe != None:
            for key, duration in self.generateTimeframe(timeframe).items():
                self.prefixAgg = " SELECT %s(%s) as agg_val from %s where " % (agg.aggfunc_notrans, self.cleanKey(agg.aggfield), self.aql_database)
                self.suffixAgg = " group by %s having agg_val %s %s LAST %s %s" % (self.cleanKey(agg.groupfield), agg.cond_op, agg.condition, duration, key)
                return self.prefixAgg, self.suffixAgg
        else:
            self.prefixAgg = " SELECT %s(%s) as agg_val from %s where " % (agg.aggfunc_notrans, self.cleanKey(agg.aggfield), self.aql_database)
            self.suffixAgg = " group by %s having agg_val %s %s" % (self.cleanKey(agg.groupfield), agg.cond_op, agg.condition)
            return self.prefixAgg, self.suffixAgg
        """
        #print(agg)
        raise NotImplementedError("The 'agg' aggregation operator is not yet implemented for this backend") 

    def generateTimeframe(self, timeframe):
        time_unit = timeframe[-1:]
        duration = timeframe[:-1]
        timeframe_object = {}
        if time_unit == "s":
            timeframe_object['seconds'] = int(duration)
        elif time_unit == "m":
            timeframe_object['minutes'] = int(duration)
        elif time_unit == "h":
            timeframe_object['hours'] = int(duration)
        elif time_unit == "d":
            timeframe_object['days'] = int(duration)
        else:
            timeframe_object['months'] = int(duration)
        return timeframe_object


    def generateBefore(self, parsed):
        if self.logname:
            return self.logname
        return self.logname

    def generate(self, sigmaparser):
        """Method is called for each sigma rule and receives the parsed rule (SigmaParser)"""
        columns = list()
        mapped =None
        #print(sigmaparser.parsedyaml)
        self.logsource = sigmaparser.parsedyaml.get("logsource") if sigmaparser.parsedyaml.get("logsource") else sigmaparser.parsedyaml.get("logsources", {})
        fields = ""
        try:
            #print(sigmaparser.parsedyaml["fields"])
            for field in sigmaparser.parsedyaml["fields"]:
                mapped = sigmaparser.config.get_fieldmapping(field).resolve_fieldname(field, sigmaparser)
                if type(mapped) == str:
                    columns.append(mapped)
                elif type(mapped) == list:
                    columns.extend(mapped)
                else:
                    raise TypeError("Field mapping must return string or list")

            fields = ",".join(str(x) for x in columns)
            fields = " | table " + fields

        except KeyError:    # no 'fields' attribute
            mapped = None
            pass

        #print("Mapped: ", mapped)
        #print(sigmaparser.parsedyaml)
        #print(sigmaparser.condparsed)
        #print("Columns: ", columns)
        #print("Fields: ", fields)
        #print("Logsource: " , self.logsource)

        for parsed in sigmaparser.condparsed:
            query = self.generateQuery(parsed, sigmaparser)
            before = self.generateBefore(parsed)
            after = self.generateAfter(parsed)

            #print("Before: ", before)

            #print("Query: ", query)

            result = ""
            if before is not None:
                result = before
            if query is not None:
                result += query
            if after is not None:
                result += after

            return result

    def generateQuery(self, parsed, sigmaparser):
        self.sigmaparser = sigmaparser
        result = self.generateNode(parsed.parsedSearch)
        """
        if any("flow" in i for i in self.parsedlogsource):
            aql_database = "flows"
        else:
            aql_database = "events"
        """
        prefix = ""
        ret = '[ { "id" : "and", "key": "And", "children" : ['
        ret2 = ' ] } ]'
        try:
            mappedFields = []
            for field in sigmaparser.parsedyaml["fields"]:
                    mapped = sigmaparser.config.get_fieldmapping(field).resolve_fieldname(field, sigmaparser)
                    #print(mapped)
                    mappedFields.append(mapped)
                    if " " in mapped and not "(" in mapped:
                        prefix += ", \"" + mapped + "\""
                    else:
                        prefix +=  ", " + mapped

        except KeyError:    # no 'fields' attribute
            mapped = None
            pass

        #if parsed.parsedAgg: #and timeframe == None:
        #    (prefix, suffixAgg) = self.generateAggregation(parsed.parsedAgg)
        #    result = prefix + result
        #    result += suffixAgg
        #elif parsed.parsedAgg != None and timeframe != None:
        #    (prefix, suffixAgg) = self.generateAggregation(parsed.parsedAgg, timeframe)
        #    result = prefix + result
        #    result += suffixAgg
        #else:
        #    result = prefix + result

        #print(result)
        #print("Prefix: ", prefix)
        # result = prefix + json.dumps(result)
        result = json.dumps(result)

        analytic_txt = ret + result + ret2 # json.dumps(ret)
        try:
            analytic = json.loads(analytic_txt) # json.dumps(ret)
        except Exception as e:
            print("Failed to parse json: %s" % analytic_txt)
            raise Exception("Failed to parse json: %s" % analytic_txt)
        # "rules","filter_name","actions_category_name","correlation_action","date_added","scores/53c9a74abfc386415a8b463e","enabled","public","group_name","score_id"

        cmt = "Sigma Rule: %s\n" % sigmaparser.parsedyaml['id'] 
        cmt += "Author: %s\n" % sigmaparser.parsedyaml['author'] 
        cmt += "Level: %s\n" % sigmaparser.parsedyaml['level'] 
        if 'falsepositives' in sigmaparser.parsedyaml and type(sigmaparser.parsedyaml['falsepositives']) is list:
            if len(sigmaparser.parsedyaml['falsepositives']) > 0:
                cmt += "False Positives: "
                for v in sigmaparser.parsedyaml['falsepositives']:
                    if v:
                        cmt += "%s, " % v
                    else:
                        cmt += "None, "
                cmt = cmt[:-2] + "\n"
        elif 'falsepositives' in sigmaparser.parsedyaml and sigmaparser.parsedyaml['falsepositives']:
            raise Exception("Unknown type for false positives: ", type(sigmaparser.parsedyaml['falsepositives']))

        if 'references' in sigmaparser.parsedyaml:
            ref = "%s\n" % "\n".join(sigmaparser.parsedyaml['references']) 
        else:
            ref = ''
        record = {
            "rules" : analytic, # analytic_txt.replace('"','""'),
            "filter_name" : sigmaparser.parsedyaml['title'],
            "actions_category_name" : "Add (+)",
            "correlation_action" : 5.00,
            "date_added" : sigmaparser.parsedyaml['date'],
            "enabled" : True,
            "public" : True,
            "comments" : cmt,
            "references" : ref,
            "group_name" : ".",
            "hawk_id" : sigmaparser.parsedyaml['id']
        }
        if 'tags' in sigmaparser.parsedyaml:
            record["tags"] = sigmaparser.parsedyaml['tags']

        if not 'status' in self.sigmaparser.parsedyaml or 'status' in self.sigmaparser.parsedyaml and self.sigmaparser.parsedyaml['status'] != 'experimental':
            record['correlation_action'] += 10.0;
        if 'falsepositives' in self.sigmaparser.parsedyaml and len(self.sigmaparser.parsedyaml['falsepositives']) > 1:
            record['correlation_action'] -= (2.0 * len(self.sigmaparser.parsedyaml['falsepositives']) )

        if 'level' in self.sigmaparser.parsedyaml:
            if self.sigmaparser.parsedyaml['level'].lower() == 'critical':
                record['correlation_action'] += 15.0;
            elif self.sigmaparser.parsedyaml['level'].lower() == 'high':
                record['correlation_action'] += 10.0;
            elif self.sigmaparser.parsedyaml['level'].lower() == 'medium':
                record['correlation_action'] += 5.0;
            elif self.sigmaparser.parsedyaml['level'].lower() == 'low':
                record['correlation_action'] += 2.0;
       
        return json.dumps(record)
