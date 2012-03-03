import hashlib
import math
from tornado.escape import utf8
from tornado.options import options
from june.lib.handler import BaseHandler
from june.lib.decorators import require_user
from june.models import Node, Topic, Reply
from june.models import MemberMixin, NodeMixin, TopicMixin


class HomeHandler(BaseHandler, MemberMixin, NodeMixin):
    def get(self):
        topics = Topic.query.order_by('-impact')[:20]
        user_ids = []
        node_ids = []
        for topic in topics:
            user_ids.append(topic.user_id)
            node_ids.append(topic.node_id)
        users = self.get_users(user_ids)
        nodes = self.get_nodes(node_ids)
        self.render('home.html', topics=topics, users=users, nodes=nodes)


class NodeHandler(BaseHandler, MemberMixin):
    def get(self, slug):
        node = Node.query.filter_by(slug=slug).first()
        if not node:
            self.send_error(404)
            return
        topics = Topic.query.order_by('-impact')[:20]
        user_ids = [topic.user_id for topic in topics]
        users = self.get_users(user_ids)
        self.render('node.html', node=node, topics=topics, users=users)


class NodeListHandler(BaseHandler, NodeMixin):
    def get(self):
        nodes = Node.query.all()
        self.render('node_list.html', nodes=nodes)


class CreateTopicHandler(BaseHandler):
    @require_user
    def get(self, slug):
        node = Node.query.filter_by(slug=slug).first()
        if not node:
            self.send_error(404)
            return
        self.render('topic_form.html', node=node, topic=None)

    @require_user
    def post(self, slug):
        node = self.db.query(Node).filter_by(slug=slug).first()
        if not node:
            self.send_error(404)
            return
        title = self.get_argument('title', None)
        content = self.get_argument('content', None)
        if not (title and content):
            self.render('topic_form.html', message='Please Fill the form')
            return
        key = hashlib.md5(utf8(content)).hexdigest()
        url = self.cache.get(key)
        # avoid double submit
        if url:
            self.redirect(url)
            return
        topic = Topic(title=title, content=content)
        topic.node_id = node.id
        topic.user_id = self.current_user.id
        node.topic_count += 1
        self.db.add(topic)
        self.db.add(node)
        self.db.commit()
        url = '/topic/%d' % topic.id
        self.cache.set(key, url, 100)
        self.redirect(url)


class TopicHandler(BaseHandler, MemberMixin, TopicMixin, NodeMixin):
    def get(self, id):
        topic = self.get_topic_by_id(id)
        if not topic:
            self.send_error(404)
            return
        node = self.get_node_by_id(topic.node_id)
        replies = Reply.query.filter_by(topic_id=id).all()
        user_ids = [o.user_id for o in replies]
        user_ids.append(topic.user_id)
        users = self.get_users(user_ids)
        if self.is_ajax():
            self.render('snippet/topic.html', topic=topic, node=node,
                        replies=replies, users=users)
            return
        self.render('topic.html', topic=topic, node=node, replies=replies,
                    users=users)

    @require_user
    def post(self, id):
        # for topic reply
        content = self.get_argument('content', None)
        if not content:
            self.redirect('/topic/%s' % id)
            return

        topic = self.db.query(Topic).filter_by(id=id).first()
        if not topic:
            self.send_error(404)
            return

        key = hashlib.md5(utf8(content)).hexdigest()
        url = self.cache.get(key)
        # avoid double submit
        if url:
            self.redirect(url)
            return

        reply = Reply(content=content)
        reply.topic_id = id
        reply.user_id = self.current_user.id
        topic.reply_count += 1
        topic.impact += self._calc_impact()
        self.db.add(reply)
        self.db.add(topic)
        self.db.commit()
        url = '/topic/%s' % id
        self.cache.set(key, url, 100)
        self.redirect(url)

    def _calc_impact(self):
        if hasattr(options, 'reply_factor_for_topic'):
            factor = int(options.reply_factor_for_topic)
        else:
            factor = 150
        return factor * int(math.log(self.current_user.reputation))


class UpTopicHandler(BaseHandler):
    @require_user
    def post(self, id):
        topic = self.db.query(Topic).filter_by(id=id).first()
        if not topic:
            self.send_error(404)
            return
        topic.impact += self._calc_impact()
        up_users = topic.up_users
        user_id = str(self.current_user.id)
        if user_id in up_users:
            topic.impact -= self._calc_impact()
            return
        up_users.append(str(self.current_user.id))
        topic.ups = ','.join(up_users)
        topic

    def _calc_impact(self):
        if hasattr(options, 'up_factor_for_topic'):
            factor = int(options.up_factor_for_topic)
        else:
            factor = 600
        return factor * int(math.log(self.current_user.reputation))


handlers = [
    ('/', HomeHandler),
    ('/nodes', NodeListHandler),
    ('/node/(\w+)', NodeHandler),
    ('/node/(\w+)/topic', CreateTopicHandler),
    ('/topic/(\d+)', TopicHandler),
]