#!/usr/bin/env python
__author__ = 'greg'
try:
    from aggregation_api import AggregationAPI,InvalidMarking
    from classification import Classification
    import clustering
    import math
    import pandas as pd
    import numpy as np
    from scipy.spatial.distance import pdist,squareform
    from scipy.cluster.hierarchy import linkage
    import abc
    import re
    import random
    import unicodedata
    import os
    import requests
    from aggregation_api import hesse_line_reduction
    from scipy import spatial
    # from termcolor import colored
    import warnings

    import matplotlib.pyplot as plt
    import matplotlib.cbook as cbook
    import rollbar
    import json
    import sys
    import yaml
    from blob_clustering import BlobClustering
    from copy import deepcopy

    import scipy.spatial.distance as ssd

except:
    # # if any errors were raised - probably because Greg thought
    # # that some Python library was standard when it actually isn't
    # # report it with rollbar (which should hopefully be installed)
    # import yaml
    # import rollbar
    #
    # panoptes_file = open("/app/config/aggregation.yml","rb")
    # api_details = yaml.load(panoptes_file)
    # rollbar_token = api_details["default"]["rollbar"]
    # rollbar.init(rollbar_token,"production")
    # rollbar.report_exc_info()

    raise

folger_replacements = {}
# with open("/home/ggdhines/alpha_folger","rb") as alpha_folger:
#     with open("/home/ggdhines/beta_folger","rb") as beta_folger:
#         for l1,l2 in zip(alpha_folger.readlines(),beta_folger.readlines()):
#             l1 = l1.strip()
#             l2 = l2.strip()
#             folger_replacements[l1] = l2


def folger_alpha_tags(text):
    assert isinstance(text,str)
    if "with" in text:
        print text
        a = True
    else:
        a = False
    for l1,l2 in folger_replacements.items():
        text = text.replace(l1,l2)

    if a:
        print text
        print
    return text

if os.path.exists("/home/ggdhines"):
    base_directory = "/home/ggdhines"
else:
    base_directory = "/home/greg"

class AbstractNode:
    def __init__(self):
        self.value = None
        self.rchild = None
        self.lchild = None

        self.parent = None
        self.depth = None
        self.height = None

        self.users = None

    def __set_parent__(self,node):
        assert isinstance(node,InnerNode)
        self.parent = node

    @abc.abstractmethod
    def __traversal__(self):
        return []

    def __set_depth__(self,depth):
        self.depth = depth


class LeafNode(AbstractNode):
    def __init__(self,value,index,user=None):
        AbstractNode.__init__(self)
        self.value = value
        self.index = index
        self.users = [user,]
        self.height = 0
        self.pts = [value,]

    def __traversal__(self):
        return [(self.value,self.index),]

class InnerNode(AbstractNode):
    def __init__(self,rchild,lchild,dist=None):
        AbstractNode.__init__(self)
        assert isinstance(rchild,(LeafNode,InnerNode))
        assert isinstance(lchild,(LeafNode,InnerNode))

        self.rchild = rchild
        self.lchild = lchild

        rchild.__set_parent__(self)
        lchild.__set_parent__(self)

        self.dist = dist

        assert (self.lchild.users is None) == (self.rchild.users is None)
        if self.lchild.users is not None:
            self.users = self.lchild.users[:]
            self.users.extend(self.rchild.users)

        self.pts = self.lchild.pts[:]
        self.pts.extend(self.rchild.pts[:])

        self.height = max(rchild.height,lchild.height)+1

    def __traversal__(self):
        retval = self.rchild.__traversal__()
        retval.extend(self.lchild.__traversal__())

        return retval


def set_depth(node,depth=0):
    assert isinstance(node,AbstractNode)
    node.__set_depth__(depth)

    if node.rchild is not None:
        set_depth(node.rchild,depth+1)
    if node.lchild is not None:
        set_depth(node.lchild,depth+1)


def lowest_common_ancestor(node1,node2):
    assert isinstance(node1,LeafNode)
    assert isinstance(node2,LeafNode)

    depth1 = node1.depth
    depth2 = node2.depth

    # make sure that the first node is the "shallower" node
    if depth1 > depth2:
        temp = node2
        node2 = node1
        node1 = temp

        depth1 = node1.depth
        depth2 = node2.depth
    while depth2 > depth1:
        node2 = node2.parent
        depth2 = node2.depth

    while node1 != node2:
        node1 = node1.parent
        node2 = node2.parent

    return node1.height


def create_clusters(ordering,maxima):
    if maxima == []:
        return [ordering,]

    next_maxima = max(maxima,key=lambda x:x[1])

    split = next_maxima[0]
    left_split = ordering[:split]
    right_split = ordering[split:]

    maxima_index = maxima.index(next_maxima)
    left_maximia = maxima[:maxima_index]
    right_maximia = maxima[maxima_index+1:]
    # need to adjust the indices for the right hand values
    right_maximia = [(i-split,j) for (i,j) in right_maximia]

    retval = create_clusters(left_split,left_maximia)
    retval.extend(create_clusters(right_split,right_maximia))

    return retval


def Levenshtein(a,b):
    "Calculates the Levenshtein distance between a and b."
    n, m = len(a), len(b)
    if n > m:
        # Make sure n <= m, to use O(min(n,m)) space
        a,b = b,a
        n,m = m,n

    current = range(n+1)
    for i in range(1,m+1):
        previous, current = current, [i]+[0]*n
        for j in range(1,n+1):
            add, delete = previous[j]+1, current[j-1]+1
            change = previous[j-1]
            if a[j-1] != b[i-1]:
                change = change + 1
            current[j] = min(add, delete, change)

    return current[n]


class TextCluster(clustering.Cluster):
    def __init__(self,shape,param_dict):
        clustering.Cluster.__init__(self,shape,param_dict)
        self.line_agreement = []

        self.tags = dict()
        tag_counter = 149

        if "tag_file" in param_dict:
            with open(param_dict["tag_file"],"rb") as f:
                for l in f.readlines():
                    self.tags[l[:-1]] = tag_counter
                    tag_counter += 1

        self.erroneous_tags = dict()

    def __line_alignment__(self,lines):
        """
        align.py the text by using MAFFT
        :param lines:
        :return:
        """

        if len(lines) == 1:
            return lines

        # todo - try to remember why I give each output file an id
        id_ = str(random.uniform(0,1))

        # with open(base_directory+"/Databases/transcribe"+id_+".fasta","wb") as f:
        with open("/tmp/transcribe"+id_+".fasta","wb") as f:
            for line in lines:
                if isinstance(line,tuple):
                    # we have a list of text segments which we should join together
                    line = "".join(line)

                # line = unicodedata.normalize('NFKD', line).encode('ascii','ignore')
                # assert isinstance(line,str)

                # for i in range(max_length-len(line)):
                #     fasta_line += "-"

                try:
                    f.write(">\n"+line+"\n")
                except UnicodeEncodeError:
                    print line
                    print unicodedata.normalize('NFKD', line).encode('ascii','ignore')
                    raise

        # todo - play around with gap penalty --op 0.5
        t = "mafft  --text /tmp/transcribe"+id_+".fasta> /tmp/transcribe"+id_+".out 2> /dev/null"
        os.system(t)

        aligned_text = []
        with open("/tmp/transcribe"+id_+".out","rb") as f:
            cumulative_line = ""
            for line in f.readlines():
                if (line == ">\n"):
                    if (cumulative_line != ""):
                        aligned_text.append(cumulative_line)
                        cumulative_line = ""
                else:
                    cumulative_line += line[:-1]

            if cumulative_line == "":
                print lines
                assert False
            aligned_text.append(cumulative_line)

        os.remove("/tmp/transcribe"+id_+".fasta")
        os.remove("/tmp/transcribe"+id_+".out")

        return aligned_text

    def __accuracy__(self,s):
        assert isinstance(s,str)
        assert len(s) > 0
        return sum([1 for c in s if c != "-"])/float(len(s))

    # todo - is this function really necessary?
    def __agreement__(self,text):
        """
        calculate the % of characters in each line of text where all characters at this position (over all lines)
        are in agreement. I ignore any starting or trailing "-" (spaces inserted for alignment)
        :param text:
        :return:
        """
        assert isinstance(text,list)
        assert len(text) > 1
        assert isinstance(text[0],str)
        assert min([len(t) for t in text]) == max([len(t) for t in text])

        retval = []

        for t in text:
            leftmost_char = -1
            rightmost_char = -1
            for i,c in enumerate(t):
                if c != "-":
                    leftmost_char = i
                    break
            for i,c in reversed(list(enumerate(t))):
                if c != "-":
                    rightmost_char = i
                    break

            agreement = 0

            for i in range(leftmost_char,rightmost_char+1):
                c = [t2[i].lower() for t2 in text]
                if min(c) == max(c):
                    assert c[0] != "-"
                    agreement += 1

            retval.append(agreement/float(rightmost_char-leftmost_char+1))
        return retval

    # todo - can probably remove this function but double check
    # def __complete_agreement__(self,text):
    #     assert isinstance(text,list)
    #     assert len(text) > 1
    #     assert isinstance(text[0],str)
    #     assert min([len(t) for t in text]) == max([len(t) for t in text])
    #
    #     agreement = 0
    #     for i in range(len(text[0])):
    #
    #         c = [t[i].lower() for t in text if t[i] != "-"]
    #         if min(c) == max(c):
    #             assert c[0] != "-"
    #             agreement += 1
    #
    #     return agreement/float(len(text[0]))

    def __set_special_characters__(self,text):
        """
        use upper case letters to represent special characters which MAFFT cannot deal with
        return a string where upper case letters all represent special characters
        "A" is used to represent all tags (all for an abitrary number of tags)
        also return a string which capitalization kept in tack and only the special tags removed
        so going from lower_text to text, allows us to recover what the captialization should have been
        """

        text = text.encode('ascii','ignore')

        # first we need to replace each tag with a one character representation
        for tag,chr_representation in self.tags.items():
            text = re.sub(tag,chr(chr_representation),text)

        # for tag,chr_representation in self.erroneous_tags.items():
        #     text = re.sub(tag,chr_representation,text)

        # we can do this afterwards because non-alphabet characters are not affected by .lower
        lower_text = text.lower()

        # then record were each tag occurs
        # tag_indices = {}
        new_lower_text = ""
        for char_index in range(len(lower_text)):
            if ord(lower_text[char_index]) > 127:
                new_lower_text += "A"
                # tag_indices[char_index] = ord(lower_text[char_index])
            else:
                new_lower_text += lower_text[char_index]
        lower_text = new_lower_text

        # take care of other characters which MAFFT cannot handle
        # note that text contains the original characters
        lower_text = re.sub(" ","I",lower_text)
        lower_text = re.sub("=","J",lower_text)
        lower_text = re.sub("\*","K",lower_text)
        lower_text = re.sub("\(","L",lower_text)
        lower_text = re.sub("\)","M",lower_text)
        lower_text = re.sub("<","N",lower_text)
        lower_text = re.sub(">","O",lower_text)
        lower_text = re.sub("-","P",lower_text)
        lower_text = re.sub("\'","Q",lower_text)

        # text = re.sub(" ",chr(160),text)
        # text = re.sub("=",chr(161),text)
        # text = re.sub("\*",chr(162),text)
        # text = re.sub("\(",chr(163),text)
        # text = re.sub("\)",chr(164),text)
        # text = re.sub("<",chr(165),text)
        # text = re.sub(">",chr(166),text)
        # text = re.sub("-",chr(167),text)

        # todo - find a way to fix this - stupid postgres/json
        # text = re.sub(r'\'',chr(168),text)

        return lower_text,text

    def __reset_special_characters__(self,text):
        """
        python/postgres seem have a bit of a problem with non-standard ascii code
        not sure why - but the easiest way to deal with this seems to be reset each non-standard ascii code
        to the tag it corresponds to
        :param text:
        :return:
        """
        # undo MAFFT special characters
        text = re.sub("I"," ",text)
        text = re.sub("J","=",text)
        text = re.sub("K","\*",text)
        text = re.sub("L","\(",text)
        text = re.sub("M","\)",text)
        text = re.sub("N","<",text)
        text = re.sub("O",">",text)
        text = re.sub("P","-",text)
        text = re.sub("Q","\'",text)

        reverse_map = {v: k for k, v in self.tags.items()}
        # also go with something different for "not sure"
        # this matter when the function is called on the aggregate text
        # reverse_map[200] = chr(27)
        # and for gaps inserted by MAFFT
        # reverse_map[201] = chr(24)

        ret_text = ""

        for c in text:
            if ord(c) > 128:
                ret_text += reverse_map[ord(c)]
            else:
                ret_text += c



        return ret_text

    def __merge_aligned_text__(self,aligned_text):
        """
        once we have aligned the text using MAFFT, use this function to actually decide on an aggregate
        result - will also return the % of agreement
        and the percentage of how many characters for each transcription agree with the agree
        handles special tags just fine - and assumes that we have dealt with capitalization already
        """
        aggregate_text = ""
        num_agreed = 0

        # will keep track of the percentage of characters from each transcription which agree
        # with the aggregate
        agreement_per_user = [0 for i in aligned_text]

        for char_index in range(len(aligned_text[0])):
            # get all the possible characters
            # todo - we can reduce this down to having to loop over each character once
            # todo - handle case (lower case vs. upper case) better
            char_set = set(text[char_index] for text in aligned_text)
            # get the percentage of votes for each character at this position
            char_vote = {c:sum([1 for text in aligned_text if text[char_index] == c])/float(len(aligned_text)) for c in char_set}
            # get the most common character (also the most likely to be the correct one) and the percentage of users
            # who "voted" for it
            most_likely_char,vote_percentage = max(char_vote.items(),key=lambda x:x[1])

            # note that the most likely char can be 201 - which corresponds to inserted gaps
            # this corresponds to the case where one or more users gave some text but the rest of
            # of the users say there wasn't anything there
            if (vote_percentage > 0.75):
                num_agreed += 1
                aggregate_text += most_likely_char

                for i in range(len(aligned_text)):
                    if aligned_text[i][char_index] == most_likely_char:
                        agreement_per_user[i] += 1
            else:
                # "Z" represents characters which we are not certain about
                aggregate_text += chr(27)

        # what percentage of characters have we reached consensus on - i.e. we are fairly confident about?
        percent_consensus = num_agreed/float(len(aggregate_text))

        # convert the agreement per user to a percentage
        agreement_per_user = [a/float(len(aggregate_text)) for a in agreement_per_user]

        return aggregate_text,percent_consensus,agreement_per_user

    def __add_alignment_spaces__(self,aligned_text_list,capitalized_text):
        """
        take the text representation where we still have upper case and lower case letters
        plus special characters for tags (so definitely not the input for MAFFT) and add in whatever
        alignment characters are needed (say char(201)) so that the first text representations are all
        aligned
        fasta is the format the MAFFT reads in from - so non_fasta_text contains non-alpha-numeric ascii chars
        pts_and_users is used to match text in aligned text with non_fasta_text
        """

        aligned_nf_text_list = []
        for text,nf_text in zip(aligned_text_list,capitalized_text):
            aligned_nf_text = ""
            i = 0
            for c in text:
                if c == "-":
                    aligned_nf_text += chr(24)
                else:
                    aligned_nf_text += nf_text[i]
                    i += 1
            aligned_nf_text_list.append(aligned_nf_text)

        return aligned_nf_text_list

    def __cluster__(self,markings,user_ids,tools,reduced_markings,image_dimensions,recusrive=False):
        print "\nstarting"
        # we want to first cluster first just on dist and theta - ignoring the text contents
        # dist_list,theta_list,text_list,raw_pts_list = zip(*markings)
        # mapped_markings = zip(dist_list,theta_list)

        # cluster just on points, not on text
        dist_l,theta_l,text_l = zip(*reduced_markings)

        reduced_markings_without_text = zip(dist_l,theta_l)
        clusters  = self.__agglomerative__clustering__(markings,reduced_markings,user_ids)
        return clusters,0

    def __cap_cluster__(self,cluster):
        # add some fields to the cluster to indicate that it is "capped", i.e. should not be merged with
        # any other clusters
        # also reset the special characters in the individual transcriptions
        # results.append({"center":center,"cluster members":pts,"tools":[],"num users":len(users),"agreement":a})
        intercepts,slopes,transcriptions = zip(*cluster["cluster members"])

        aligned_transcriptions = self.__line_alignment__(transcriptions)
        # take the alignment spaces inserted by MAFFT, and apply them to the non-FASTA text

        nf_aligned_lines = self.__add_alignment_spaces__(aligned_transcriptions,cluster["individual transcriptions"])
        aggregate_text,character_agreement,per_user_agreement = self.__merge_aligned_text__(nf_aligned_lines)

        aggregate_text = self.__reset_special_characters__(aggregate_text)

        x1_values,x2_values,y1_values,y2_values = zip(*cluster["coordinates"])

        x1 = np.median(x1_values)
        x2 = np.median(x2_values)
        y1 = np.median(y1_values)
        y2 = np.median(y2_values)
        assert max([ord(c) for c in aggregate_text]) < 200

        cluster["center"] = (x1,x2,y1,y1,aggregate_text)
        cluster["tools"] = []
        cluster["num users"] = len(cluster["cluster members"])

        cluster["cluster members"] = []
        for coord,text in zip(cluster["coordinates"],cluster["individual transcriptions"]):
            text = self.__reset_special_characters__(text)
            # coord = list(coord)
            # coord.append(text)
            cluster["cluster members"].append((coord,text))

        # since cluster["individual transcriptions"] might have bad characters in it, let's delete it
        del cluster["individual transcriptions"]
        return cluster

    def __normalize_lines__(self,intercepts,slopes):
        """
        normalize the lines so that the intercepts and slopes are all between 0 and 1
        makes cluster better
        also returns a dictionary which allows us to "unnormalize" lines so that we refer to the original values
        """
        # min_intercept,max_intercept = min(intercepts),max(intercepts)
        # min_slopes,max_slopes = min(slopes),max(slopes)
        #
        # if max_intercept > max_intercept:
        #     normalized_intercepts = [(i-min_intercept)/(max_intercept-min_intercept) for i in intercepts]
        # else:
        #     normalized_intercepts = [1 for i in intercepts]
        #
        # if max_slopes > min_slopes:
        #     normalized_slopes = [(i-min_slopes)/(max_slopes-min_slopes) for i in slopes]
        # else:
        #     normalized_slopes = [1 for i in slopes]

        mean_intercept = np.mean(intercepts)
        std_intercept = np.std(intercepts)

        normalized_intercepts = [(i-mean_intercept)/std_intercept for i in intercepts]

        mean_slopes = np.mean(slopes)
        std_slopes = np.std(slopes)

        normalized_slopes = [(s-mean_slopes)/std_slopes for s in slopes]

        return normalized_intercepts,normalized_slopes

    def __agglomerative__clustering__(self,markings,reduced_markings,user_ids):
        """
        TBD
        """
        # start by splitting markings into lines and text and then the lines into slopes and intercepts
        intercepts,slopes,text = zip(*reduced_markings)

        # deal with special characters in the text and "recombine" the markings
        # text has capital letters used only for special characters/tags
        # while capitalized_text has the original capitalization which is useful for the final aggregate result
        text,capitalized_text = zip(*[self.__set_special_characters__(t) for t in text])
        reduced_markings = zip(intercepts,slopes,text)

        l = []
        for ii,t in enumerate(text):
            # print t
            if "finished" in t:
                l.append(ii)

        print "==="

        # normalize the the slopes and intercepts
        normalized_intercepts,normalized_slopes = self.__normalize_lines__(intercepts,slopes)
        pts_list = zip(normalized_intercepts,normalized_slopes)
        # pts_list = zip(intercepts,slopes)

        # do agglomerative clustering
        # the panda dataframe seems necessary but not totally sure
        # labels = range(len(pts_list))
        # print labels
        # variables = ["X","Y"]
        # df = pd.DataFrame(list(pts_list),columns=variables, index=labels)
        # row_dist = pd.DataFrame(squareform(pdist(df, metric='euclidean')), columns=labels, index=labels)

        # see http://stackoverflow.com/questions/18952587/use-distance-matrix-in-scipy-cluster-hierarchy-linkage
        labels = range(len(pts_list))
        variables = ["X","Y"]
        # X = np.random.random_sample([5,3])*10
        df = pd.DataFrame(list(pts_list),columns=variables, index=labels)



        # variables = ["X"]
        # # X = np.random.random_sample([5,3])*10
        # df = pd.DataFrame(list(normalized_intercepts),columns=variables, index=labels)

        row_dist = pd.DataFrame(squareform(pdist(df, metric='euclidean')), columns=labels, index=labels)
        distances = squareform(pdist(df, metric='euclidean'))[l[0]]
        distances = zip(range(len(distances)),distances)
        distances.sort(key = lambda x:x[1])
        print distances
        for ii,d in distances[:10]:
            print text[ii]
        print "==-----"


        agglomerations = linkage(row_dist, method='single')
        print len(pts_list)
        print len(agglomerations)
        assert False

        # clusters will be a list representation of the the tree that results from merging clusters
        # as determined by agglomerations
        clusters = []
        for m,M,raw_transcription in zip(reduced_markings,capitalized_text,markings):
            # coordinates will store the xy coordinates of the line segment
            c = {"cluster members":[m,],"individual transcriptions":[M,], "coordinates":[raw_transcription[:-1]]}
            clusters.append(c)

        # go through of the cluster mergers given by the scipy algorithm
        # and decide whether to go with them or not
        for merge in agglomerations:
            rchild_index = int(merge[0])
            lchild_index = int(merge[1])



            print lchild_index,rchild_index

            # None => we have already capped every path in the subtree
            # i.e. on any path from this node down to the root, we will encounter a capped cluster
            # so if both nodes are capped, just add None and continue
            if (clusters[rchild_index] is None) and (clusters[lchild_index] is None):
                clusters.append(None)
                continue
            # if only one node is None, cap the node that is not None
            elif clusters[rchild_index] is None:
                clusters[lchild_index] = self.__cap_cluster__(clusters[lchild_index])
                clusters.append(None)
                continue
            elif clusters[lchild_index] is None:
                clusters[rchild_index] = self.__cap_cluster__(clusters[rchild_index])
                clusters.append(None)
                continue

            assert "center" not in clusters[lchild_index]
            assert "center" not in clusters[rchild_index]

            # todo - I think this use of cluster members is consistent - but not consistent with code
            # todo - else where - won't cause a bug, but could cause some confusion
            _,_,transcriptions = zip(*(clusters[rchild_index]["cluster members"]))
            _,_,transcriptions_left = zip(*(clusters[lchild_index]["cluster members"]))

            # if True in [("surely" in t) for t in transcriptions]:
            #     print rchild_index,lchild_index
            #     print clusters[rchild_index]["cluster members"]
            #     print clusters[lchild_index]["cluster members"]
            #     print
            # elif True in [("surely" in t) for t in transcriptions_left]:
            #     print rchild_index,lchild_index
            #     print clusters[rchild_index]["cluster members"]
            #     print clusters[lchild_index]["cluster members"]
            #     print

            # convert to list
            transcriptions = list(transcriptions)
            transcriptions.extend(transcriptions_left)

            aligned_transcriptions = self.__line_alignment__(transcriptions)
            accuracy = self.__agreement__(aligned_transcriptions)

            # if the minimum accuracy is reasonably high, then we will want to combine them
            if min(accuracy) >= 0.6:
                new_cluster = deepcopy(clusters[rchild_index])
                new_cluster["cluster members"].extend(clusters[lchild_index]["cluster members"])
                new_cluster["individual transcriptions"].extend(clusters[lchild_index]["individual transcriptions"])
                new_cluster["coordinates"].extend(clusters[lchild_index]["coordinates"])
                clusters.append(new_cluster)
            else:
                # the accuracy of the combined cluster is low enough that we do not want combine
                # instead, we'll "cap" each of the clusters - by giving it a center value
                # and appending None to the list of clusters
                clusters[rchild_index] = self.__cap_cluster__(clusters[rchild_index])
                clusters[lchild_index] = self.__cap_cluster__(clusters[lchild_index])
                clusters.append(None)

        capped_clusters = []
        for c in clusters:
            if (c is not None) and ("center" in c):
                if c["num users"] >= 3:
                    print "***"
                    capped_clusters.append(c)
                else:
                    print hesse_line_reduction([c["center"],])[0][:2],c["center"][-1]

        return capped_clusters

# def text_mapping(marking,image_dimensions):
#     # want to extract the params x1,x2,y1,y2 but
#     # ALSO make sure that x1 <= x2 and flip if necessary
#
#     x1 = marking["startPoint"]["x"]
#     x2 = marking["endPoint"]["x"]
#     y1 = marking["startPoint"]["y"]
#     y2 = marking["endPoint"]["y"]
#
#     try:
#         text = marking["text"]
#     except KeyError:
#         raise InvalidMarking(marking)
#
#     if x1 <= x2:
#         return x1,x2,y1,y2,text
#     else:
#         return x2,x1,y2,y1,text


def relevant_text_params(marking,image_dimensions):
    """
    extract the relevant params from the the transcription marking
    note that the text is the last item - which means we can treat the results
    pretty much like a line segment - which it mostly is
    :param marking:
    :param image_dimensions:
    :return:
    """
    if ("startPoint" not in marking) or ("endPoint" not in marking):
        raise InvalidMarking(marking)
    x1 = marking["startPoint"]["x"]
    y1 = marking["startPoint"]["y"]
    x2 = marking["endPoint"]["x"]
    y2 = marking["endPoint"]["y"]

    if min(x1,x2,y1,y2) < 0:
        raise InvalidMarking(marking)

    if "text" not in marking:
        raise InvalidMarking(marking)

    text = marking["text"]

    if x1 <= x2:
        return x1,x2,y1,y2,text
    else:
        return x2,x2,y2,y1,text


def text_line_reduction(line_segments):
    """
    use if we want to cluster based on Hesse normal form - but want to retain the original values
    :param line_segment:
    :return:
    """
    reduced_markings = []

    for line_seg in line_segments:
        x1,y1,x2,y2,text = line_seg

        x2 += random.uniform(-0.0001,0.0001)
        x1 += random.uniform(-0.0001,0.0001)

        dist = (x2*y1-y2*x1)/math.sqrt((y2-y1)**2+(x2-x1)**2)

        try:
            tan_theta = math.fabs(y1-y2)/math.fabs(x1-x2)
            theta = math.atan(tan_theta)
        except ZeroDivisionError:
            theta = math.pi/2.

        reduced_markings.append((dist,theta,text))

    return reduced_markings


class SubjectRetirement(Classification):
    def __init__(self,environment,param_dict):
        Classification.__init__(self,environment)
        assert isinstance(param_dict,dict)

        # to retire subjects, we need a connection to the host api, which hopefully is provided
        self.host_api = None
        self.project_id = None
        self.token = None
        self.workflow_id = None
        for key,value in param_dict.items():
            if key == "host":
                self.host_api = value
            elif key == "project_id":
                self.project_id = value
            elif key == "token":
                self.token = value
            elif key == "workflow_id":
                self.workflow_id = value

        assert (self.host_api is not None) and (self.project_id is not None) and (self.token is not None) and (self.workflow_id is not None)

    def __aggregate__(self,raw_classifications,workflow,aggregations):
        # start by looking for empty subjects

        to_retire = set()
        for subject_id in raw_classifications["T0"]:
            user_ids,is_subject_empty = zip(*raw_classifications["T0"][subject_id])
            if is_subject_empty != []:
                empty_count = sum([1 for i in is_subject_empty if i == True])/float(len(is_subject_empty))
                if (len(is_subject_empty) > 5) and (empty_count >= 0.8):
                    to_retire.add(subject_id)

        blank_retirement = len(to_retire)

        non_blanks = []

        # now look to see if everything has been transcribed
        for subject_id in raw_classifications["T3"]:
            user_ids,completely_transcribed = zip(*raw_classifications["T3"][subject_id])

            if sum([1 for i in completely_transcribed]) >= 3:
                to_retire.add(subject_id)
                non_blanks.append(subject_id)

            # # have at least 4/5 of the last 5 people said the subject has been completely transcribed?
            # recent_completely_transcribed = completely_transcribed[-5:]
            # if recent_completely_transcribed != []:
            #     complete_count = sum([1 for i in recent_completely_transcribed if i == True])/float(len(recent_completely_transcribed))
            #
            #     if (len(recent_completely_transcribed) == 5) and (complete_count >= 0.8):
            #         to_retire.add(subject_id)

        # don't retire if we are in the development environment
        if (to_retire != set()) and (self.environment != "development"):
            try:
                headers = {"Accept":"application/vnd.api+json; version=1","Content-Type": "application/json", "Authorization":"Bearer "+self.token}
                params = {"retired_subjects":list(to_retire)}
                # r = requests.post("https://panoptes.zooniverse.org/api/workflows/"+str(self.workflow_id)+"/links/retired_subjects",headers=headers,json=params)
                r = requests.post("https://panoptes.zooniverse.org/api/workflows/"+str(self.workflow_id)+"/links/retired_subjects",headers=headers,data=json.dumps(params))
                # rollbar.report_message("results from trying to retire subjects","info",extra_data=r.text)

            except TypeError as e:
                print e
                rollbar.report_exc_info()
        if self.environment == "development":
            print "we would have retired " + str(len(to_retire))
            print "with non-blanks " + str(len(to_retire)-blank_retirement)
            print non_blanks

        return aggregations


class Tate(AggregationAPI):
    def __init__(self,project_id,environment):
        AggregationAPI.__init__(self,project_id,environment)#"tate")#"tate",environment="staging")
        # the code to extract the relevant params froma  text json file

        self.marking_params_per_shape["text"] = relevant_text_params
        # the code to cluster lines together
        self.default_clustering_algs["text"] = TextCluster
        self.default_clustering_algs["image"] = BlobClustering
        # the code for reducing a line segment (4d) into a 2d object
        # todo - can probably replace this with the standard for line segments
        # self.reduction_algs["text"] = text_line_reduction

        # load in the tag file
        api_details = yaml.load(open("/app/config/aggregation.yml","rb"))
        try:
            tag_file = api_details[self.project_id]["tags"]
            self.additional_clustering_args = {"text": {"reduction":text_line_reduction,"tag_file":tag_file}}
        except:
            self.additional_clustering_args = {"text": {"reduction":text_line_reduction}}

        self.ignore_versions = True
        # self.instructions[683] = {}
        self.instructions[121] = {}

        self.only_retired_subjects = False
        self.only_recent_subjects = True

        self.rollbar_token = None

    def __setup__(self):
        AggregationAPI.__setup__(self)
        self.__set_classification_alg__(SubjectRetirement,{"host":self.host_api,"project_id":self.project_id,"token":self.token,"workflow_id":121})

    def __enter__(self):
        if self.environment != "development":
            panoptes_file = open("/app/config/aggregation.yml","rb")
            api_details = yaml.load(panoptes_file)
            self.rollbar_token = api_details[self.environment]["rollbar"]
            rollbar.init(self.rollbar_token,self.environment)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # if (self.rollbar_token is not None) and (self.environment != "development") and (exc_type is not None):
        #     rollbar.report_exc_info()

            # return True
        pass

    def __cluster_output_with_colour__(self,workflow_id,ax,subject_id):
        """
        use colour to show where characters match and don't match between different transcriptions of
        the same text
        :param subject_id:
        :return:
        """
        selection_stmt = "SELECT aggregation FROM aggregations WHERE workflow_id = " + str(workflow_id) + " AND subject_id = " + str(subject_id)
        cursor = self.postgres_session.cursor()
        cursor.execute(selection_stmt)

        aggregated_text = cursor.fetchone()[0]["T2"]["text clusters"].values()
        assert isinstance(aggregated_text,list)
        # remove the list of all users
        aggregated_text = [a for a in aggregated_text if isinstance(a,dict)]

        # sort the text by y coordinates (should give the order in which the text is supposed to appear)
        aggregated_text.sort(key = lambda x:x["center"][2])

        for text in aggregated_text:
            ax.plot([text["center"][0],text["center"][1]],[text["center"][2],text["center"][3]],color="red")
            actual_text = text["center"][-1]
            atomic_text = self.cluster_algs["text"].__set_special_characters__(actual_text)[1]

            for c in atomic_text:
                if ord(c) == 27:
                    # no agreement was reached
                    print chr(8) + unicode(u"\u2224"),
                elif ord(c) == 28:
                    # the agreement was that nothing was here
                    # technically not a space but close enough
                    print chr(8) + " ",
                else:
                    print chr(8) + c,
            print

    def __readin_tasks__(self,workflow_id):
        if self.project_id == 245:
            # marking_tasks = {"T2":["image"]}
            marking_tasks = {"T2":["text","image"]}
            # todo - where is T1?
            classification_tasks = {"T3" : True}

            return classification_tasks,marking_tasks
        elif self.project_id == 376:
            marking_tasks = {"T2":["text"]}
            classification_tasks = {}

            return classification_tasks,marking_tasks
        else:
            return AggregationAPI.__readin_tasks__(self,workflow_id)

    def __plot_individual_points__(self,subject_id,task_id,shape):
        print self.cluster_algs["text"]

    def __get_subjects_to_aggregate__(self,workflow_id,with_expert_classifications=None):
        """
        override the retired subjects function to get only subjects which have been transcribed since we last ran
        the code
        :param workflow_id:
        :param with_expert_classifications:
        :return:
        """
        recently_classified_subjects = set()
        select = "SELECT subject_id,created_at from classifications where project_id="+str(self.project_id)

        for r in self.cassandra_session.execute(select):
            subject_id = r.subject_id
            if r.created_at >= self.old_time:
                recently_classified_subjects.add(subject_id)
        # assert False
        return list(recently_classified_subjects)

    def __prune__(self,aggregations):
        assert isinstance(aggregations,dict)
        for task_id in aggregations:
            if task_id == "param":
                continue

            if isinstance(aggregations[task_id],dict):
                for cluster_type in aggregations[task_id]:
                    if cluster_type == "param":
                        continue

                    del aggregations[task_id][cluster_type]["all_users"]
                    for cluster_index in aggregations[task_id][cluster_type]:
                        if cluster_index == "param":
                            continue

        return aggregations

retired_subjects = [649216, 649217, 649218, 649219, 649220, 649222, 649223, 649224, 649225, 671754, 649227, 649228, 649229, 649230, 667309, 662872, 649234, 653332, 649239, 653336, 671769, 673482, 653339, 649244, 649245, 649246, 649248, 653346, 653348, 653349, 665642, 653356, 649261, 649262, 649263, 671752, 649267, 671796, 649269, 649270, 649272, 649226, 653316, 649281, 669763, 669765, 669766, 669769, 653390, 649231, 669793, 650598, 649233, 662887, 667764, 662890, 649362, 649363, 649365, 649366, 649368, 663705, 649370, 649371, 649372, 649373, 663710, 663711, 671904, 671905, 649378, 665627, 663717, 671910, 671911, 671912, 663722, 663723, 649388, 663726, 663727, 673480, 663730, 671923, 649397, 671927, 649400, 671932, 667338, 671936, 653344, 671938, 673483, 671940, 665634, 649426, 669923, 669926, 669927, 669932, 669933, 669937, 649461, 669942, 649463, 671992, 669946, 669947, 649258, 649470, 669951, 649472, 669954, 669955, 669957, 649478, 669960, 669962, 671447, 649484, 669965, 649486, 669969, 649490, 669972, 669976, 649497, 669978, 669981, 669982, 669984, 669985, 669987, 649508, 669989, 649510, 649265, 669992, 672896, 669995, 649505, 649518, 649519, 649520, 649521, 649522, 649523, 649524, 649525, 649526, 649527, 649528, 649529, 649530, 649531, 649532, 649533, 649534, 649535, 672283, 649537, 649538, 649540, 649541, 649542, 649543, 649544, 649545, 672081, 672083, 672084, 672086, 672087, 649564, 649573, 672102, 662929, 672104, 672106, 649592, 649601, 663939, 663940, 672136, 672834, 671811, 673518, 653381, 649639, 649644, 670127, 649653, 649578, 662945, 649647, 662948, 649511, 649728, 649744, 649745, 649747, 664089, 664090, 664091, 672284, 672285, 672286, 662961, 672297, 649780, 672310, 672313, 649788, 649793, 649798, 649828, 650342, 672360, 649836, 672366, 650344, 649845, 649848, 672385, 649858, 672409, 649890, 649892, 662641, 649900, 672541, 649907, 672439, 672443, 672885, 649922, 649937, 649942, 649944, 664301, 664303, 649369, 650366, 664313, 603264, 649995, 664334, 603268, 664346, 664349, 603270, 672551, 672554, 603271, 653341, 672558, 672561, 672562, 603273, 672906, 672907, 672567, 664396, 664403, 649387, 653114, 668518, 668522, 672915, 664454, 664463, 664469, 664471, 664473, 664474, 664488, 649374, 672714, 668628, 671909, 650212, 670700, 650688, 671914, 671915, 666640, 649390, 671919, 672797, 649462, 672803, 672808, 672809, 672810, 672814, 672815, 672817, 661465, 652344, 652347, 652354, 653010, 672858, 650336, 672870, 662632, 650346, 672875, 650349, 650352, 650353, 650355, 650357, 650358, 650360, 650361, 650363, 603262, 603263, 650368, 650369, 672898, 650371, 650372, 650374, 650375, 650377, 650378, 603275, 672909, 603279, 603280, 603281, 603283, 662676, 603285, 603288, 649466, 650400, 603297, 603299, 603300, 650411, 650413, 667334, 672952, 649608, 672968, 672973, 672977, 672980, 672295, 653015, 670979, 670993, 670998, 671007, 671014, 671017, 671019, 671022, 671024, 671030, 671034, 671036, 671037, 662847, 671042, 662851, 671047, 671048, 671061, 662870, 671064, 662874, 650590, 671073, 650594, 650596, 671078, 671079, 650602, 671083, 662894, 662895, 671088, 671089, 662898, 671091, 662901, 671094, 671099, 671101, 671102, 662922, 671115, 662924, 662926, 671119, 667024, 671121, 671125, 671126, 671128, 671129, 662941, 662943, 662944, 671137, 671138, 662947, 671140, 662949, 662950, 662951, 662953, 662955, 662956, 662958, 662959, 671153, 671154, 671156, 662910, 671158, 671161, 671163, 649203, 671168, 671170, 671173, 671174, 673481, 671179, 650701, 671184, 671640, 671189, 650636, 671994, 671198, 653364, 649467, 671204, 671206, 671208, 671209, 671220, 671222, 649471, 671230, 671232, 649474, 671249, 671253, 649477, 671267, 671269, 650797, 649480, 671282, 650809, 649482, 671296, 671302, 671303, 653239, 671330, 653240, 671327, 667234, 667238, 667240, 667242, 667244, 667248, 667252, 667258, 649496, 649498, 663204, 667303, 667305, 667306, 667307, 667308, 663213, 667313, 667315, 667318, 671417, 667322, 667324, 667326, 649504, 667331, 667332, 667333, 663238, 667335, 667336, 667337, 663242, 663243, 653004, 663245, 673486, 671442, 653011, 667350, 667351, 667352, 671449, 671452, 671453, 663262, 649509, 673505, 663268, 663269, 663270, 649213, 663278, 673520, 649512, 663282, 663283, 650537, 649514, 663296, 649515, 671939, 671510, 653273, 663323, 663324, 663326, 650544, 663330, 663334, 663335, 663337, 671532, 653307, 673594, 653279, 673606, 671565, 673614, 671568, 673620, 665435, 653149, 653151, 653152, 653154, 671588, 662844, 671594, 673672, 653310, 653294, 671638, 665495, 665496, 671727, 673693, 649200, 670022, 653231, 651185, 653234, 651187, 671671, 651192, 651193, 653243, 651197, 671678, 649205, 671680, 651201, 653250, 651203, 665540, 653253, 671686, 653257, 665547, 653260, 671693, 665550, 665551, 653304, 653270, 665559, 663512, 665561, 665564, 671709, 661471, 665569, 653283, 653285, 671718, 653288, 671721, 671722, 653291, 649198, 649199, 653296, 649201, 649202, 653299, 671733, 649206, 649207, 649208, 649209, 649211, 649212, 653309, 649214, 649215]
import random
random.seed(0)
retired_subjects = retired_subjects[:200]

if __name__ == "__main__":
    with Tate(sys.argv[1],sys.argv[2]) as project:
        # project.__migrate__()
        project.__aggregate__(subject_set=[671541])
        # print aggregated_text