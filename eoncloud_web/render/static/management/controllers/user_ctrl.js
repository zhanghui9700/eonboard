/**
 * User: bluven
 * Date: 15-6-29
 * Time: 下午2:11
 **/

CloudApp.controller('UserController',
    function($rootScope, $scope, $filter, $modal, $i18next, $ngBootbox,
             CommonHttpService, ToastrService, ngTableParams,
             CheckboxGroup, ngTableHelper, User){

        $scope.$on('$viewContentLoaded', function(){
                Metronic.initAjax();
        });

        $scope.users = [];
        var checkboxGroup = $scope.checkboxGroup = CheckboxGroup.init($scope.users);

        $scope.user_table = new ngTableParams({
                page: 1,
                count: 10
            },{
                counts: [],
                getData: function ($defer, params) {
                    User.query(function (data) {
                        $scope.users = ngTableHelper.paginate(data, $defer, params);
                        checkboxGroup.syncObjects($scope.users);
                    });
                }
            });

        $scope.deactivate = function(user){

            bootbox.confirm($i18next('user.confirm_deactivate'), function(confirmed){

                if(!confirmed){
                    return;
                }

                CommonHttpService.post("/api/users/deactivate/", {id: user.id}).then(function(data){
                    if (data.success) {
                        ToastrService.success(data.msg, $i18next("success"));
                        $scope.user_table.reload();
                    } else {
                        ToastrService.error(data.msg, $i18next("op_failed"));
                    }
                });

            });
        };

        $scope.activate = function(user){
            bootbox.confirm($i18next('user.confirm_activate'), function(confirmed){

                if(!confirmed){
                    return;
                }

                CommonHttpService.post("/api/users/activate/", {id: user.id}).then(function(data){
                    if (data.success) {
                        ToastrService.success(data.msg, $i18next("success"));
                        $scope.user_table.reload();
                    } else {
                        ToastrService.error(data.msg, $i18next("op_failed"));
                    }
                });

            });
        };

        $scope.viewUdcList = function(user){
            $modal.open({
                templateUrl: 'udc_list.html',
                controller: 'UserUdcListController',
                backdrop: "static",
                size: 'lg',
                resolve: {
                    user: function(){
                        return User.get({id: user.id});
                    }
                }
            });
        };

        var openBroadcastModal = function(users){
            $modal.open({
                templateUrl: 'broadcast.html',
                controller: 'BroadcastController',
                backdrop: "static",
                size: 'lg',
                resolve: {
                    users: function(){
                        return users;
                    },
                    notificationOptions: function(){
                        return CommonHttpService.get('/api/notifications/options/');
                    }
                }
            }).result.then(function(){
                   checkboxGroup.uncheck();
            });
        };

        $scope.openBroadcastModal = function(){
            openBroadcastModal(checkboxGroup.checkedObjects());
        };

        $scope.openNotifyModal = function(user){
            openBroadcastModal([user]);
        };

        $scope.openDataCenterBroadcastModal = function(){
            $modal.open({
                templateUrl: 'data_center_broadcast.html',
                controller: 'DataCenterBroadcastController',
                backdrop: "static",
                size: 'lg',
                resolve: {
                    notificationOptions: function(){
                        return CommonHttpService.get('/api/notifications/options/');
                    }
                }
            });
        };

        $scope.openAnnounceModal = function(){
            $modal.open({
                templateUrl: 'announce.html',
                controller: 'AnnounceController',
                backdrop: "static",
                size: 'lg',
                resolve: {
                    notificationOptions: function(){
                        return CommonHttpService.get('/api/notifications/options/');
                    }
                }
            });
        };

        $scope.initialize = function(user){

            $ngBootbox.confirm($i18next("user.confirm_initialize")).then(function(){
                CommonHttpService.post("/api/users/initialize/", {user_id: user.id}).then(function(data){
                    if (data.success) {
                        ToastrService.success(data.msg, $i18next("success"));
                        $scope.user_table.reload();
                    } else {
                        ToastrService.error(data.msg, $i18next("op_failed"));
                    }
                });
            });
        };

        $scope.openNewUserModal = function(){
            $modal.open({
                templateUrl: 'new-user.html',
                backdrop: "static",
                controller: 'NewUserController',
                size: 'lg'
            }).result.then(function(){
                $scope.user_table.reload();
            });
        };
    })

    .controller('UserUdcListController',
        function($scope, $modalInstance, ngTableParams, user){

            $scope.cancel = $modalInstance.dismiss;

            $scope.udc_table = new ngTableParams({
                    page: 1,
                    count: 10
                },{
                    counts: [],
                    getData: function ($defer, params) {
                        user.$promise.then(function(){
                            $defer.resolve(user.user_data_centers);
                        });
                }
            });
    })

    .controller('BroadcastController',
        function($scope, $modalInstance, $i18next, ngTableParams,
                 CommonHttpService, ValidationTool, ToastrService,
                 users, notificationOptions){

            var INFO = 1, form = null, options = [];

            angular.forEach(notificationOptions, function(option){
                options.push({key: option[0], label: [option[1]]});
            });

            $scope.users = users;
            $scope.options = options;
            $scope.cancel = $modalInstance.dismiss;
            $scope.notification = {title: '', content: '', level: INFO};

            $modalInstance.rendered.then(function(){
                form = ValidationTool.init('#notificationForm');
            });

            $scope.broadcast = function(notification){

                if(!form.valid()){
                    return;
                }

                var params = angular.copy(notification);

                if(users.length > 0){
                    params.receiver_ids = [];
                    angular.forEach(users, function(user){
                        params.receiver_ids.push(user.id);
                    });
                }

                CommonHttpService.post('/api/notifications/broadcast/', params).then(function(result){
                    if(result.success){
                        ToastrService.success(result.msg, $i18next("success"));
                        $modalInstance.close();
                    } else {
                        ToastrService.error(result.msg, $i18next("op_failed"));
                    }
                });
            }
    })

    .controller('DataCenterBroadcastController',
        function($scope, $modalInstance, $i18next, ngTableParams,
                CommonHttpService, ValidationTool, ToastrService,
                DataCenter, notificationOptions){

        var INFO = 1, form = null, options = [];

        angular.forEach(notificationOptions, function(option){
            options.push({key: option[0], label: [option[1]]});
        });

        $scope.options = options;
        $scope.cancel = $modalInstance.dismiss;
        $scope.notification = {title: '', content: '', data_centers: [], level: INFO};
        $scope.data_centers = DataCenter.query(function(data_centers){
            $scope.notification.data_center = data_centers[0].id;
        });

        $modalInstance.rendered.then(function(){
            form = ValidationTool.init('#notificationForm');
        });

        $scope.broadcast = function(notification){

            if(!form.valid()){
                return;
            }

            var params = angular.copy(notification);

            CommonHttpService.post('/api/notifications/data-center-broadcast/', params).then(function(result){
                if(result.success){
                    ToastrService.success(result.msg, $i18next("success"));
                    $modalInstance.close();
                } else {
                    ToastrService.error(result.msg, $i18next("op_failed"));
                }
            });
        }
    })

    .controller('AnnounceController',
        function($scope, $modalInstance, $i18next,
                 CommonHttpService, ValidationTool, ToastrService,
                 notificationOptions){

            var INFO = 1, form = null, options = [];

            angular.forEach(notificationOptions, function(option){
                options.push({key: option[0], label: [option[1]]});
            });

            $scope.options = options;
            $scope.cancel = $modalInstance.dismiss;
            $scope.notification = {title: '', content: '', level: INFO};

            $modalInstance.rendered.then(function(){
                form = ValidationTool.init('#notificationForm');
            });

            $scope.announce = function(notification){

                if(!form.valid()){
                    return;
                }

                var params = angular.copy(notification);

                CommonHttpService.post('/api/notifications/announce/', params).then(function(result){
                    if(result.success){
                        ToastrService.success(result.msg, $i18next("success"));
                        $modalInstance.close();
                    } else {
                        ToastrService.error(result.msg, $i18next("op_failed"));
                    }
                });
            }
    })

    .controller('NewUserController',
        function($scope, $modalInstance, $i18next,
                 CommonHttpService, ToastrService, UserForm){

            var form = null;
            $modalInstance.rendered.then(function(){
                form = UserForm.init();
            });

            $scope.user = {};
            $scope.cancel = $modalInstance.dismiss;
            $scope.create = function(){

                if(form.valid() == false){
                    return;
                }

                CommonHttpService.post('/api/account/create/', $scope.user).then(function(result){
                    if(result.success){
                        ToastrService.success(result.msg, $i18next("success"));
                        $modalInstance.close();
                    } else {
                        ToastrService.error(result.msg, $i18next("op_failed"));
                    }
                });
            };
        }
    )
    .factory('UserForm', ['ValidationTool', '$i18next', function(ValidationTool, $i18next) {
        return {
            init: function(){

                var config = {

                    rules: {
                        username: {
                            required: true,
                            remote: {
                                url: "/api/account/is-name-unique/",
                                data: {
                                    username: $("#username").val()
                                },
                                async: false
                            }
                        },
                        email: {
                            required: true,
                            email: true,
                            remote: {
                                url: "/api/account/is-email-unique/",
                                data: {
                                    email: $("#email").val()
                                },
                                async: false
                            }
                        },
                        mobile: {
                            required: true,
                            digits: true,
                            minlength:11,
                            maxlength:11,
                            remote: {
                                url: "/api/account/is-mobile-unique/",
                                data: {
                                    mobile: $("#mobile").val()
                                },
                                async: false
                            }
                        },
                        password1: {
                            required: true,
                            complexPassword: true
                        },
                        password2: {
                            required: true,
                            equalTo: "#password1"
                        }
                    },
                    messages: {
                        username: {
                            remote: $i18next('user.name_is_used')
                        },
                        email: {
                            remote: $i18next('user.email_is_used')
                        },
                        mobile: {
                            remote: $i18next('user.mobile_is_used')
                        }
                    }
                };
                return ValidationTool.init('#userForm', config);
            }
        }}]);
